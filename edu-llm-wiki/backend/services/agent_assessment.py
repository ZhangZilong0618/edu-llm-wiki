"""Server-owned assessment cards used by the conversational tutor.

The standalone test routes remain the source of truth for question generation
and objective grading. This module adds a small persistent card layer so a
chat answer can be graded against the answer that was actually issued by the
server, then fed into the BKT/SM-2 observer exactly once per attempt id.
"""

from __future__ import annotations

import json
import re
import uuid
import asyncio
from typing import Any

from models.tests import TestCreateRequest, TestQuestion, TestSession
from services.graph_store import connect, get_nodes, make_node_id
from services.mastery import queue_for_user, record_attempt
from services.search_engine import keyword_search
from storage.wiki_store import list_wiki_pages, read_wiki_page


# Conversational practice must remain responsive even when the configured
# model is offline or takes too long to answer. The persisted fallback card
# lets the learner continue and keeps grading/BKT/SM-2 available locally.
QUESTION_GENERATION_TIMEOUT_SECONDS = 10.0


def _now() -> float:
    import time

    return time.time()


def _answer_text(value: str | list[str]) -> str:
    return "；".join(str(v) for v in value) if isinstance(value, list) else str(value or "")


def _resolve_kc(project_id: str, related: str | None, fallback: str | None = None) -> str:
    if related:
        if related.endswith(".md"):
            return make_node_id(project_id, related)
        for node in get_nodes(project_id):
            if related in {node.get("id"), node.get("page_path"), node.get("label"), node.get("title")}:
                return node["id"]
    if fallback:
        return fallback
    pages = list_wiki_pages(project_id=project_id)
    return make_node_id(project_id, pages[0]["path"] if pages else "chat-practice")


def _row_question(row) -> dict:
    return {
        "id": row["question_id"],
        "question_id": row["question_id"],
        "session_id": row["session_id"],
        "kc_id": row["kc_id"],
        "prompt": row["prompt"],
        "type": row["question_type"],
        "options": json.loads(row["options_json"] or "[]"),
        "difficulty": row["difficulty"] or "mixed",
        "related_page": row["related_page"],
        "concepts": json.loads(row["concepts_json"] or "[]"),
        "hints": json.loads(row["hints_json"] or "[]"),
    }


def get_question(project_id: str, user_id: str, question_id: str) -> tuple[dict, dict] | None:
    with connect(project_id) as conn:
        row = conn.execute(
            "SELECT * FROM agent_questions WHERE project_id=? AND user_id=? AND question_id=?",
            (project_id, user_id, question_id),
        ).fetchone()
    if not row:
        return None
    question = _row_question(row)
    question["_answer"] = json.loads(row["answer_json"] or '""')
    question["explanation"] = row["explanation"] or ""
    return question, dict(row)


def get_assessment_context(project_id: str, user_id: str, question_id: str) -> dict | None:
    """Load a question and its latest graded attempt for a chat follow-up.

    The browser supplies only the question id. Prompt, options, expected answer,
    explanation, and grading details are resolved from server-owned records.
    """
    found = get_question(project_id, user_id, question_id)
    if not found:
        return None
    question, _row = found
    context = {
        "question_id": question_id,
        "prompt": question["prompt"],
        "type": question.get("type"),
        "options": question.get("options") or [],
        "related_page": question.get("related_page"),
        "concepts": question.get("concepts") or [],
        "difficulty": question.get("difficulty"),
        "answered": False,
    }
    with connect(project_id) as conn:
        attempt = conn.execute(
            """SELECT answer_json,score,max_score,feedback,result_json
               FROM agent_attempts
               WHERE project_id=? AND user_id=? AND question_id=?
               ORDER BY created_at DESC LIMIT 1""",
            (project_id, user_id, question_id),
        ).fetchone()
    if not attempt:
        return context

    result = json.loads(attempt["result_json"] or "{}")
    context.update({
        "answered": True,
        "learner_answer": json.loads(attempt["answer_json"] or '""'),
        "score": float(attempt["score"] or 0),
        "max_score": float(attempt["max_score"] or 1),
        "correct": bool(result.get("correct", False)),
        "feedback": attempt["feedback"] or result.get("feedback") or "",
        "correct_answer": result.get("correct_answer", question.get("_answer")),
        "explanation": question.get("explanation") or result.get("explanation") or "",
        "learning_update": result.get("learning_update") or {},
    })
    return context


def get_attempt(project_id: str, user_id: str, attempt_id: str) -> dict | None:
    with connect(project_id) as conn:
        row = conn.execute(
            "SELECT result_json FROM agent_attempts WHERE project_id=? AND user_id=? AND attempt_id=?",
            (project_id, user_id, attempt_id),
        ).fetchone()
    return json.loads(row[0]) if row and row[0] else None


def _topic_pages(project_id: str, topic: str) -> list[dict]:
    """Find the Wiki page most directly about a conversational topic."""
    pages = list_wiki_pages(project_id=project_id)
    query = re.sub(r"\s+", " ", topic or "").strip()
    if not query:
        return []
    normalized_query = re.sub(r"[\s\W_]+", "", query).lower()

    # Exact/containing title matches are important for short Chinese topics
    # such as “元素”, which keyword tokenizers may otherwise discard.
    title_matches = []
    for page in pages:
        if page.get("type") in {
            "teaching_object", "teaching_object_group", "teaching_index",
            "learner_profile", "learning_event_log",
        }:
            continue
        title = str(page.get("title") or "")
        path = str(page.get("path") or "")
        if path.startswith(("learning/", "teaching/")):
            continue
        normalized_title = re.sub(r"[\s\W_]+", "", title).lower()
        normalized_path = re.sub(r"[\s\W_]+", "", path).lower()
        if normalized_query and (
            normalized_query in normalized_title or normalized_query in normalized_path
        ):
            # Prefer the most specific title, and exact matches over broader
            # containing matches.
            title_matches.append((
                0 if normalized_title == normalized_query else 1,
                abs(len(normalized_title) - len(normalized_query)),
                page,
            ))
    title_matches.sort(key=lambda item: (item[0], item[1]))
    if title_matches:
        return [item[2] for item in title_matches[:3]]

    # When the topic came from prior dialogue, prioritize titles mentioned
    # most recently. This binds a vague “出个题考考我” to the active subject.
    normalized_dialogue = re.sub(r"\s+", "", query).lower()
    mentioned = []
    for page in pages:
        title = re.sub(r"\s+", "", str(page.get("title") or "")).lower()
        if str(page.get("path") or "").startswith(("learning/", "teaching/")):
            continue
        if len(title) >= 2 and title in normalized_dialogue:
            mentioned.append((normalized_dialogue.rfind(title), len(title), page))
    mentioned.sort(key=lambda item: (item[0], item[1]), reverse=True)
    if mentioned:
        return [item[2] for item in mentioned[:3]]

    try:
        ranked = keyword_search(query, top_k=3, project_id=project_id)
    except Exception:
        ranked = []
    by_path = {page.get("path"): page for page in pages}
    return [by_path[result.get("path")] for result in ranked if result.get("path") in by_path]


def _context_for_request(
    project_id: str,
    page_path: str | None,
    kc_id: str | None,
    topic: str | None = None,
) -> tuple[str, str | None]:
    pages = []
    if page_path:
        page = read_wiki_page(page_path, project_id=project_id)
        if page:
            pages = [page]
    if not pages and topic:
        pages = _topic_pages(project_id, topic)
    if not pages:
        # TeachingObject directories and learner activity pages are generated
        # for every project, but they are system projections rather than
        # course material.  Including them in the default practice context
        # makes a brand-new, empty project issue questions about
        # ``ExerciseAttempt`` or ``LearningState`` instead of telling the
        # learner to import material.  Keep explicit page scopes available
        # for users who intentionally study one of those pages.
        excluded_types = {
            "teaching_object",
            "teaching_object_group",
            "teaching_index",
            "learner_profile",
            "learning_event_log",
        }
        summaries = list_wiki_pages(project_id=project_id)
        summaries = [
            summary for summary in summaries
            if summary.get("type") not in excluded_types
            and not str(summary.get("path", "")).startswith("learning/")
            and not str(summary.get("path", "")).startswith("teaching/")
        ]
        for summary in summaries[:8]:
            page = read_wiki_page(summary["path"], project_id=project_id)
            if page:
                pages.append(page)
    if not pages:
        return "", page_path
    context = "\n\n---\n\n".join(
        f"### {p.get('title') or p['path']}\nPath: {p['path']}\n{p.get('content', '')[:5000]}"
        for p in pages
    )
    return context, pages[0]["path"]


def _fallback_question(context: str, related_page: str | None, difficulty: str) -> TestQuestion:
    """Build a self-contained card when question generation is unavailable.

    A generic short-answer prompt is impossible to grade reliably without
    knowledge context. Use an objective card instead, so the local grader is
    authoritative even when no LLM is configured or reachable.
    """
    title = "当前知识库"
    evidence = ""
    if context.strip():
        heading = re.search(r"###\s+([^\n]+)", context)
        if heading:
            title = heading.group(1).split("\n", 1)[0].strip() or title
        body = re.sub(r"^###.*$|^Path:.*$", "", context, flags=re.MULTILINE)
        body = re.sub(r"[#>*`\[\](){}]", " ", body)
        body = re.sub(r"\s+", " ", body).strip()
        # Keep the evidence short enough for a compact card while preserving
        # one complete sentence for the explanation.
        evidence = re.split(r"(?<=[。！？.!?])\s*", body, maxsplit=1)[0].strip()
        evidence = evidence[:180]

    if evidence:
        prompt = f"关于“{title}”，下面哪一项符合当前 Wiki 页面内容？"
        options = [
            evidence,
            "该页面只讨论账号登录设置。",
            "该页面没有任何可学习内容。",
        ]
        explanation = f"页面内容提到：{evidence}"
        related = related_page
    else:
        prompt = "当前知识库还没有可用于出题的材料，下一步应该做什么？"
        options = ["先导入学习材料", "直接提交空答案", "关闭学习路径"]
        explanation = "请先在 Import 中导入课程材料，再回到对话中出题。"
        related = None

    return TestQuestion(
        id="fallback",
        type="multiple_choice",
        prompt=prompt,
        options=options,
        answer="A",
        explanation=explanation,
        related_page=related,
        difficulty=difficulty,
    )


async def create_question(
    project_id: str,
    user_id: str,
    *,
    mode: str = "practice",
    session_id: str | None = None,
    page_path: str | None = None,
    kc_id: str | None = None,
    topic: str | None = None,
    difficulty: str = "mixed",
    question_types: list[str] | None = None,
    card_style: str = "",
) -> dict:
    """Generate and persist one question, preferring the due review queue.

    ``question_types`` narrows generation to the learner's named card type
    ("出个选择题" → ["multiple_choice"]); None lets the generator mix freely.
    ``card_style="true_false"`` renders a 判断题 as a multiple-choice card
    with exactly two options (正确/错误) — the card system has no separate
    true/false type, so the style is enforced through the generation prompt.
    """
    review_card: TestQuestion | None = None
    review_card_session: str | None = None
    if mode == "review":
        # Review is always backed by a due SM-2 card. A page/KC scope narrows
        # the queue; it must never turn review into an unscheduled practice
        # question merely because a page happens to be selected in the UI.
        due = queue_for_user(project_id, user_id, limit=100)
        if page_path:
            due = [item for item in due if item.get("path") == page_path]
        if kc_id:
            due = [item for item in due if item.get("kc_id") == kc_id]
        if not due:
            # Review is a due-card workflow.  Returning a structured empty
            # state lets clients explain that there is nothing due instead of
            # silently issuing a new practice card that changes the learner's
            # review queue semantics.
            return {
                "session_id": session_id,
                "question": None,
                "status": "empty",
                "message": "当前没有到期复习卡。先完成一道练习，之后再回来复习。",
                "due_count": 0,
            }
        page_path = page_path or due[0].get("path") or None
        kc_id = kc_id or due[0].get("kc_id") or None

        # A review turn should reopen the card that became due. Generating a
        # fresh question here would leave the original due card untouched and
        # make the learner answer a different item than the SM-2 scheduler
        # selected. Prefer the most recently issued server-owned card for the
        # due KC/path; older projects may have no persisted card, in which case
        # the normal generation/fallback path below remains available.
        with connect(project_id) as conn:
            row = conn.execute(
                """SELECT * FROM agent_questions
                   WHERE project_id=? AND user_id=? AND kc_id=?
                   ORDER BY created_at DESC LIMIT 1""",
                (project_id, user_id, kc_id),
            ).fetchone()
        if row:
            stored = _row_question(row)
            stored["_answer"] = json.loads(row["answer_json"] or '""')
            stored["explanation"] = row["explanation"] or ""
            review_card = TestQuestion(
                id=stored["question_id"],
                type=stored["type"],
                prompt=stored["prompt"],
                options=stored["options"],
                answer=stored["_answer"],
                explanation=stored["explanation"],
                related_page=stored["related_page"],
                concepts=stored["concepts"],
                difficulty=stored["difficulty"],
            )
            review_card_session = stored["session_id"]

    context, related_page = _context_for_request(project_id, page_path, kc_id, topic)
    question: TestQuestion | None = review_card
    # A due review card is authoritative: the learner must see and answer
    # the same prompt/answer pair that the scheduler selected. Only practice
    # turns generate a fresh card from the current Wiki context.
    if context and review_card is None:
        # Import lazily to avoid making the chat router depend on route import
        # order. The standalone generator already validates JSON and types.
        from routes.tests import _generate_questions

        prompt_topic = (topic or "").strip()
        if "\n" in prompt_topic or len(prompt_topic) > 80:
            heading = re.search(r"(?m)^###\s+([^\n]+)", context)
            prompt_topic = heading.group(1).strip() if heading else ""
        instructions = []
        if prompt_topic:
            instructions.append(f"围绕《{prompt_topic}》出题，题目必须主要考查这个主题，不要考查其他知识点。")
        if card_style == "true_false":
            instructions.append(
                "题型为判断题：题干必须是一个完整、可独立判断对错的陈述句，"
                "options 固定为且仅为两项：[\"A. 正确\", \"B. 错误\"]，"
                "answer 只能是 A 或 B。严禁出四个选项的选择题。"
            )
        req = TestCreateRequest(
            question_count=1,
            question_types=question_types or ["short_answer", "multiple_choice", "fill_blank"],
            difficulty=difficulty,
            page_path=page_path,
            node_id=kc_id,
            natural_prompt=("".join(instructions) or None),
            mode="practice",
        )
        try:
            generated = await asyncio.wait_for(
                _generate_questions(req, project_id, 0, context),
                timeout=QUESTION_GENERATION_TIMEOUT_SECONDS,
            )
        except Exception:
            # A practice turn is a user-facing chat skill. Any provider or
            # parsing failure should degrade to the deterministic card below,
            # rather than turning the chat request into a 500 or a long hang.
            generated = []
        if generated:
            question = generated[0]
            if not question.related_page:
                question.related_page = related_page
    if question is None:
        # Keep the fallback objective and self-contained. This prevents a
        # vague placeholder answer from being sent to an LLM grader and then
        # marked wrong merely because the model has no useful reference.
        question = _fallback_question(context, related_page, difficulty)

    # Reuse the stored card/session for review; practice always gets a fresh
    # server-owned id so each turn is independently gradable.
    question_id = question.id if review_card is not None else uuid.uuid4().hex
    session_id = review_card_session if review_card is not None else (session_id or uuid.uuid4().hex[:12])
    resolved_kc = _resolve_kc(project_id, question.related_page or related_page, kc_id)
    hints = ["先回忆定义中的关键词。", "再说明它与相邻概念的区别。"]
    if review_card is None:
        with connect(project_id) as conn:
            conn.execute(
            """INSERT INTO agent_questions(
                project_id,user_id,question_id,session_id,kc_id,prompt,question_type,
                options_json,answer_json,explanation,related_page,concepts_json,
                difficulty,hints_json,mode,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    project_id, user_id, question_id, session_id, resolved_kc,
                    question.prompt, question.type, json.dumps(question.options, ensure_ascii=False),
                    json.dumps(question.answer, ensure_ascii=False), question.explanation,
                    question.related_page, json.dumps(question.concepts, ensure_ascii=False),
                    question.difficulty, json.dumps(hints, ensure_ascii=False), mode, _now(),
                ),
            )
    else:
        # A due review reopens the server-owned card that the scheduler chose.
        # Persist the current delivery mode on that card so submitting the
        # answer is projected as ``review_completed`` (rather than being
        # mistaken for a fresh practice attempt).  The card's prompt and
        # answer remain unchanged and are still read only from the server.
        with connect(project_id) as conn:
            conn.execute(
                "UPDATE agent_questions SET mode=? WHERE project_id=? AND user_id=? AND question_id=?",
                (mode, project_id, user_id, question_id),
            )
    # Wiki projection is aggregate and best-effort; the persisted card remains
    # authoritative even if the Markdown filesystem is unavailable.
    try:
        from services.wiki_auto_update import record_question as project_question

        project_question(
            project_id,
            user_id,
            question_id=question_id,
            kc_id=resolved_kc,
            related_page=question.related_page or related_page,
            mode=mode,
            event_id=f"{session_id}:{question_id}",
        )
    except Exception:
        pass
    return {
        "session_id": session_id,
        "question": {
            "id": question_id,
            "question_id": question_id,
            "session_id": session_id,
            "kc_id": resolved_kc,
            "prompt": question.prompt,
            "type": question.type,
            "options": question.options,
            "related_page": question.related_page,
            "concepts": question.concepts,
            "difficulty": question.difficulty,
            "hints": hints,
        },
    }


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", "", _answer_text(value)).strip().lower()


async def submit_answer(
    project_id: str,
    user_id: str,
    *,
    question_id: str,
    answer: str | list[str],
    confidence: int | None,
    hint_ladder: int,
    attempt_id: str,
) -> dict:
    previous = get_attempt(project_id, user_id, attempt_id)
    if previous is not None:
        return previous
    found = get_question(project_id, user_id, question_id)
    if found is None:
        raise KeyError("question_not_found")
    question, row = found
    stored_question = TestQuestion(
        id=question_id,
        type=question["type"],
        prompt=question["prompt"],
        options=question["options"],
        answer=question["_answer"],
        explanation=question["explanation"],
        related_page=question["related_page"],
        concepts=question["concepts"],
        difficulty=question["difficulty"],
    )
    # Keep objective grading and short-answer rubric evaluation aligned with
    # the standalone test workflow. The shared short-answer grader already
    # has a local fallback for an unavailable LLM.
    from routes.tests import _score_objective, _score_short_answers

    graded = _score_objective(stored_question, answer)
    if stored_question.type == "short_answer":
        session = TestSession(
            id=row["session_id"] or "chat-practice",
            title="Conversational practice",
            questions=[stored_question],
            created_at="",
        )
        await _score_short_answers(session, [graded], {question_id: answer})
    score = float(graded.score)
    feedback = graded.feedback
    base_payload = {
        "attempt_id": attempt_id,
        "question_id": question_id,
        "score": score,
        "max_score": 1.0,
        "correct": score >= 0.7,
        "feedback": feedback,
        "correct_answer": question["_answer"],
        "explanation": question["explanation"],
        "answer": answer,
    }
    result = await __import__("asyncio").to_thread(
        record_attempt,
        project_id,
        user_id,
        row["kc_id"],
        score=score,
        max_score=1.0,
        response=_answer_text(answer),
        expected=_answer_text(question["_answer"]),
        confidence=confidence,
        hint_ladder=max(0, int(hint_ladder)),
        attempt_id=attempt_id,
        idempotency_key=attempt_id,
        idempotency_data=base_payload,
    )
    # Learning state is authoritative; the wiki projection is best effort and
    # idempotent by attempt_id. A markdown failure must never turn a graded
    # answer into an HTTP error.
    try:
        projection_update = (result or {}).get("learning_update", {})
        row_mode = row["mode"] or "practice"
        if row_mode == "review":
            from services.wiki_auto_update import record_review as project_review

            await __import__("asyncio").to_thread(
                project_review,
                project_id,
                user_id,
                review_id=attempt_id,
                kc_id=row["kc_id"],
                related_page=question.get("related_page"),
                evaluation=base_payload,
                learning_update=projection_update,
            )
        else:
            from services.wiki_auto_update import record_attempt as project_attempt

            await __import__("asyncio").to_thread(
                project_attempt,
                project_id,
                user_id,
                attempt_id=attempt_id,
                question_id=question_id,
                kc_id=row["kc_id"],
                related_page=question.get("related_page"),
                evaluation=base_payload,
                learning_update=projection_update,
                mode=row_mode,
            )
    except Exception:
        pass
    return result
