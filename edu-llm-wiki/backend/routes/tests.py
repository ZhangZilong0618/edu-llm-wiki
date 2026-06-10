"""Standalone test sessions for staged learning assessment."""

import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from config import settings
from models.tests import TestAnswerRequest, TestAttempt, TestCreateRequest, TestQuestion, TestSession, TestSummary
from services.language import language_instruction
from services.llm_client import chat_complete
from storage.wiki_store import list_wiki_pages, read_wiki_page, validate_project_id

router = APIRouter(prefix="/api/tests", tags=["tests"])

QUESTION_TYPES = {"multiple_choice", "fill_blank", "short_answer"}


GENERATE_TEST_PROMPT = """你是 Edu-LLM-Wiki 的测验出题助手。你的任务是根据 wiki 内容生成阶段性测试题，不是聊天。

要求：
- 只返回 JSON，不要 markdown fence，不要解释。
- 题目必须基于给定 wiki 内容，避免编造无关知识。
- 题型要多样，符合 requested_types。
- multiple_choice 必须提供 4 个选项，格式为 A. ... / B. ... / C. ... / D. ...，answer 写正确选项字母。
- fill_blank 的 prompt 使用 ____ 表示空，answer 可以是字符串或字符串数组。
- short_answer 的 answer 写参考答案要点。
- explanation 要能教学，指出关键原理或理由。
- 数学公式用 LaTeX：行内 $...$，块级 $$...$$。

多样性硬性要求（必须遵守）：
- 同一份请求中每道题都要从不同角度切入：概念辨析 / 数值计算 / 适用边界与失效条件 / 易错陷阱 / 真实应用案例，至少覆盖 3 种不同视角。
- 题面、考查点、所用数据/公式、选项表述都必须各自不同，绝不允许"换皮"重复。
- 如果 user 提示里给出了"最近已出过的题面"，必须主动绕开那些角度，不要与之重复或高度相似。
- 同一 seed 字段相同的请求之间要刻意拉开差异；seed 不同则视为全新一批题目，不要参考任何之前的结果。

JSON schema:
{
  "questions": [
    {
      "type": "multiple_choice|fill_blank|short_answer",
      "prompt": "题干",
      "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
      "answer": "A",
      "explanation": "解析",
      "concepts": ["知识点"],
      "difficulty": "basic|understanding|application|mixed",
      "related_page": "可选，wiki 页面路径"
    }
  ]
}
"""

CHECK_SHORT_ANSWERS_PROMPT = """你是 Edu-LLM-Wiki 的测试批改助手。请按参考答案和上下文批改简答题。

要求：
- 只返回 JSON，不要 markdown，不要解释。
- score 是 0 到 1 的小数。
- level 只能是 empty、weak、partial、good。
- feedback 要具体指出学生答对了什么、缺什么。

JSON schema:
{
  "results": [
    {"question_id": "id", "score": 0.0, "level": "empty|weak|partial|good", "feedback": "反馈"}
  ]
}
"""


def _tests_dir(project_id: str) -> Path:
    validate_project_id(project_id)
    path = Path(settings.projects_dir) / project_id / "tests"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _session_path(session_id: str, project_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", session_id):
        raise HTTPException(status_code=400, detail="Invalid test id")
    return _tests_dir(project_id) / f"{session_id}.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_session(session_id: str, project_id: str) -> TestSession:
    path = _session_path(session_id, project_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Test session not found")
    return TestSession.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _write_session(session: TestSession, project_id: str) -> None:
    _session_path(session.id, project_id).write_text(
        json.dumps(session.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _extract_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            raise
        return json.loads(match.group(0))


def _section(content: str, names: tuple[str, ...]) -> str:
    names_pattern = "|".join(re.escape(name) for name in names)
    match = re.search(rf"##\s*(?:{names_pattern})\s*\n([\s\S]*?)(?=\n##\s+|\Z)", content, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[#*_`>$\\{}[\]().,，。；;：:！？!?-]", " ", text or "")).strip().lower()


def _parse_options(text: str) -> list[str]:
    options: list[str] = []
    for line in (text or "").splitlines():
        clean = line.strip()
        if re.match(r"^[A-Ha-h][\.\)、:：]\s+", clean):
            options.append(clean)
    return options


def _normalize_choice(value: str | list[str]) -> str:
    raw = value[0] if isinstance(value, list) and value else value
    match = re.search(r"[A-Ha-h]", str(raw or ""))
    return match.group(0).upper() if match else ""


def _normalize_blank_values(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in re.split(r"[,，;；\n]+", str(value or "")) if part.strip()]


def _is_same_answer(user: str, answer: str) -> bool:
    u = _plain(user)
    a = _plain(answer)
    return bool(u and a and (u == a or u in a or a in u))


def _question_from_exercise(page: dict, index: int, allowed_types: set[str], difficulty: str) -> TestQuestion | None:
    content = page.get("content", "")
    exercise_type = (_section(content, ("题型", "Type")) or "").lower()
    question = _section(content, ("题目", "Question", "Problem")) or content[:1200]
    options = _parse_options(_section(content, ("选项", "Options", "Choices")))
    solution = _section(content, ("解答", "答案", "Answer", "Solution"))
    if not question.strip():
        return None

    if "multiple" in exercise_type or "choice" in exercise_type or "选择" in exercise_type or options:
        qtype = "multiple_choice"
    elif "blank" in exercise_type or "填空" in exercise_type or re.search(r"____|（\s*）|\(\s*\)", question):
        qtype = "fill_blank"
    else:
        qtype = "short_answer"
    if qtype not in allowed_types:
        return None

    answer: str | list[str]
    if qtype == "multiple_choice":
        match = re.search(r"(?:答案[:：]?\s*)?([A-Ha-h])(?:[\.\)、:：\s]|$)", solution)
        answer = match.group(1).upper() if match else ""
    elif qtype == "fill_blank":
        answer = re.sub(r"^\s*(?:答案[:：]?\s*)?[A-Ha-h][\.\)、:：\s]*", "", solution).strip()
    else:
        answer = solution.strip()

    return TestQuestion(
        id=f"q{index}",
        type=qtype,
        prompt=question.strip(),
        options=options,
        blanks=max(1, len(re.findall(r"____|（\s*）|\(\s*\)", question))) if qtype == "fill_blank" else 0,
        answer=answer,
        explanation=solution.strip(),
        related_page=page.get("path"),
        concepts=[str(tag) for tag in page.get("tags", [])][:6],
        difficulty=difficulty,
    )


def _recent_question_prompts(project_id: str, limit: int = 20) -> list[str]:
    """Collect recent question prompts from stored test sessions, newest first.

    Used as negative examples in the LLM prompt to encourage diversity between
    consecutive test generations for the same wiki content.
    """
    prompts: list[tuple[str, str]] = []
    for path in _tests_dir(project_id).glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        created = str(data.get("created_at") or "")
        for question in data.get("questions", []) or []:
            prompt_text = str(question.get("prompt") or "").strip()
            if prompt_text:
                prompts.append((created, prompt_text))
    prompts.sort(key=lambda item: item[0], reverse=True)
    return [text for _, text in prompts[:limit]]


def _candidate_context(req: TestCreateRequest, project_id: str) -> tuple[list[TestQuestion], str]:
    allowed_types = set(req.question_types or []) & QUESTION_TYPES or QUESTION_TYPES
    pages = list_wiki_pages(project_id=project_id)
    extracted: list[TestQuestion] = []
    context_parts: list[str] = []

    for summary in pages:
        page = read_wiki_page(summary["path"], project_id=project_id)
        if not page:
            continue
        if req.scope == "source" and req.source and req.source not in (page.get("sources", []) or []):
            continue
        # Exercise pages are no longer lifted verbatim into the new test — the
        # generator now produces fresh questions from the concept/formula/principle
        # context below, which avoids regenerating identical items.
        if page.get("page_type") in {"concept", "formula", "principle", "source", "synthesis"} and len(context_parts) < 24:
            context_parts.append(
                f"### {page['title']} ({page['page_type']})\n路径：{page['path']}\n来源：{', '.join(page.get('sources', []) or [])}\n{page.get('content', '')[:1800]}"
            )
    return extracted[: req.question_count], "\n\n".join(context_parts)


async def _generate_questions(req: TestCreateRequest, project_id: str, existing_count: int, context: str, recent_prompts: list[str] | None = None) -> list[TestQuestion]:
    needed = max(0, req.question_count - existing_count)
    if needed <= 0:
        return []
    if not context.strip():
        return []

    seed = (req.seed or "").strip() or f"auto-{uuid.uuid4().hex[:8]}"
    recent_block = "\n".join(f"- {text[:200]}" for text in (recent_prompts or [])) or "无"

    user = f"""请生成 {needed} 道测试题。

scope: {req.scope}
source: {req.source or "全部"}
requested_types: {", ".join(req.question_types)}
difficulty: {req.difficulty}
seed: {seed}

最近已出过的题面（请避免重复或高度相似）：
{recent_block}

Wiki 内容：
{context[:22000]}
"""
    raw = await chat_complete(
        system_prompt=f"{GENERATE_TEST_PROMPT}\n\n{language_instruction()}",
        messages=[{"role": "user", "content": user}],
        temperature=0.8,
        max_tokens=3500,
        response_format={"type": "json_object"},
    )
    data = _extract_json(raw)
    questions: list[TestQuestion] = []
    for item in data.get("questions", []):
        if not isinstance(item, dict):
            continue
        qtype = str(item.get("type") or "short_answer")
        if qtype not in QUESTION_TYPES:
            qtype = "short_answer"
        options = [str(opt).strip() for opt in item.get("options", []) if str(opt).strip()] if isinstance(item.get("options"), list) else []
        if qtype == "multiple_choice" and len(options) < 2:
            qtype = "short_answer"
        prompt = str(item.get("prompt") or "").strip()
        if not prompt:
            continue
        questions.append(TestQuestion(
            id=f"q{existing_count + len(questions) + 1}",
            type=qtype,
            prompt=prompt,
            options=options,
            blanks=max(1, len(re.findall(r"____|（\s*）|\(\s*\)", prompt))) if qtype == "fill_blank" else 0,
            answer=item.get("answer") if isinstance(item.get("answer"), list) else str(item.get("answer") or ""),
            explanation=str(item.get("explanation") or ""),
            related_page=str(item.get("related_page") or "") or None,
            concepts=[str(c) for c in item.get("concepts", []) if str(c).strip()][:8] if isinstance(item.get("concepts"), list) else [],
            difficulty=str(item.get("difficulty") or req.difficulty),
        ))
    return questions[:needed]


def _score_objective(question: TestQuestion, answer: str | list[str]) -> TestAttempt:
    if question.type == "multiple_choice":
        correct = _normalize_choice(question.answer)
        user = _normalize_choice(answer)
        ok = bool(correct and user == correct)
        return TestAttempt(
            question_id=question.id,
            user_answer=answer,
            score=1 if ok else 0,
            level="good" if ok else "weak",
            feedback="回答正确。" if ok else "选项不正确，请对照解析复习。",
            correct_answer=question.answer,
        )

    if question.type == "fill_blank":
        user_values = _normalize_blank_values(answer)
        correct_values = _normalize_blank_values(question.answer)
        if not user_values:
            score = 0
        elif not correct_values:
            score = 0
        else:
            hits = sum(1 for expected in correct_values if any(_is_same_answer(user, expected) for user in user_values))
            score = hits / max(1, len(correct_values))
        return TestAttempt(
            question_id=question.id,
            user_answer=answer,
            score=round(score, 2),
            level="good" if score >= 0.85 else "partial" if score > 0 else "weak",
            feedback="填空匹配参考答案。" if score >= 0.85 else "部分匹配，请检查关键词、公式或单位。" if score > 0 else "未匹配到参考答案要点。",
            correct_answer=question.answer,
        )

    return TestAttempt(question_id=question.id, user_answer=answer, correct_answer=question.answer)


async def _score_short_answers(session: TestSession, attempts: list[TestAttempt], answers: dict[str, str | list[str]]) -> None:
    pending = [q for q in session.questions if q.type == "short_answer"]
    if not pending:
        return

    items = []
    for q in pending:
        user_answer = answers.get(q.id, "")
        if not str(user_answer or "").strip():
            for attempt in attempts:
                if attempt.question_id == q.id:
                    attempt.level = "empty"
                    attempt.feedback = "未作答。"
            continue
        items.append({
            "question_id": q.id,
            "question": q.prompt,
            "student_answer": user_answer,
            "reference_answer": q.answer,
            "explanation": q.explanation,
        })
    if not items:
        return

    try:
        raw = await chat_complete(
            system_prompt=f"{CHECK_SHORT_ANSWERS_PROMPT}\n\n{language_instruction()}",
            messages=[{"role": "user", "content": json.dumps({"items": items}, ensure_ascii=False)}],
            temperature=0.1,
            max_tokens=1800,
            response_format={"type": "json_object"},
        )
        data = _extract_json(raw)
        by_id = {str(item.get("question_id")): item for item in data.get("results", []) if isinstance(item, dict)}
    except Exception:
        by_id = {}

    for attempt in attempts:
        q = next((question for question in pending if question.id == attempt.question_id), None)
        if not q:
            continue
        result = by_id.get(q.id)
        if result:
            score = max(0, min(1, float(result.get("score") or 0)))
            level = str(result.get("level") or "partial")
            attempt.score = round(score, 2)
            attempt.level = level if level in {"empty", "weak", "partial", "good"} else "partial"
            attempt.feedback = str(result.get("feedback") or "已完成 AI 批改。")
        else:
            user_text = _plain(str(attempt.user_answer or ""))
            ref_terms = [term for term in re.split(r"\s+", _plain(str(q.answer))) if len(term) >= 2][:20]
            hits = sum(1 for term in ref_terms if term in user_text)
            score = min(1, hits / max(4, len(ref_terms[:8])))
            attempt.score = round(score, 2)
            attempt.level = "good" if score >= 0.8 else "partial" if score > 0 else "weak"
            attempt.feedback = "已按参考答案关键词进行本地估分；AI 批改不可用时会使用该兜底。"


@router.get("", response_model=list[TestSummary])
async def list_tests(project_id: str = Query("default")) -> list[TestSummary]:
    sessions: list[TestSummary] = []
    for path in _tests_dir(project_id).glob("*.json"):
        try:
            session = TestSession.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        sessions.append(TestSummary(
            id=session.id,
            title=session.title,
            status=session.status,
            question_count=len(session.questions),
            score=session.score,
            max_score=session.max_score,
            created_at=session.created_at,
            submitted_at=session.submitted_at,
        ))
    sessions.sort(key=lambda item: item.created_at, reverse=True)
    return sessions


@router.post("", response_model=TestSession)
async def create_test(req: TestCreateRequest, project_id: str = Query("default")) -> TestSession:
    extracted, context = _candidate_context(req, project_id)
    recent_prompts = _recent_question_prompts(project_id, limit=20)
    generated = await _generate_questions(req, project_id, len(extracted), context, recent_prompts)
    questions = (extracted + generated)[: req.question_count]
    if not questions:
        raise HTTPException(status_code=400, detail="No wiki content available to create a test")

    for index, question in enumerate(questions, start=1):
        question.id = f"q{index}"

    session = TestSession(
        id=uuid.uuid4().hex[:12],
        title=req.title or f"测试 {datetime.now().strftime('%m-%d %H:%M')}",
        scope=req.scope,
        source=req.source,
        mode=req.mode,
        difficulty=req.difficulty,
        questions=questions,
        created_at=_now(),
    )
    _write_session(session, project_id)
    return session


@router.get("/{session_id}", response_model=TestSession)
async def get_test(session_id: str, project_id: str = Query("default")) -> TestSession:
    return _read_session(session_id, project_id)


@router.post("/{session_id}/submit", response_model=TestSession)
async def submit_test(session_id: str, req: TestAnswerRequest, project_id: str = Query("default")) -> TestSession:
    session = _read_session(session_id, project_id)
    attempts: list[TestAttempt] = []
    for question in session.questions:
        answer = req.answers.get(question.id, "")
        attempts.append(_score_objective(question, answer))

    await _score_short_answers(session, attempts, req.answers)

    max_score = float(len(session.questions))
    score = round(sum(attempt.score for attempt in attempts), 2)
    session.attempts = attempts
    session.score = score
    session.max_score = max_score
    session.status = "submitted"
    session.submitted_at = _now()
    _write_session(session, project_id)
    return session


@router.delete("/{session_id}")
async def delete_test(session_id: str, project_id: str = Query("default")):
    path = _session_path(session_id, project_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Test session not found")
    path.unlink()
    return {"status": "deleted", "id": session_id}
