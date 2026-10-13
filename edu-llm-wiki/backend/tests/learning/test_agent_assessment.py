"""Chat assessment cards must be server-graded and idempotent."""

from __future__ import annotations

import asyncio
import json

from config import settings
from services.agent_assessment import create_question, submit_answer
from services.graph_store import connect, ensure_schema
from storage.wiki_store import ensure_dirs, write_wiki_page


def test_chat_answer_reuses_server_card_and_deduplicates_attempt(tmp_path, monkeypatch):
    project_id = "chat-assessment"
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    ensure_schema(project_id)
    write_wiki_page(
        "concepts/energy.md",
        title="Energy",
        page_type="concept",
        content="# Energy\n\nEnergy is the capacity to do work.",
        project_id=project_id,
    )

    async def fake_generate(req, project_id, existing_count, context, coverage=None):
        from models.tests import TestQuestion

        return [TestQuestion(
            id="generated", type="short_answer", prompt="Define energy.",
            answer="Energy is capacity to do work", explanation="Energy enables work.",
            related_page="concepts/energy.md", difficulty="basic",
        )]

    monkeypatch.setattr("routes.tests._generate_questions", fake_generate)
    card = asyncio.run(create_question(project_id, "learner", page_path="concepts/energy.md"))
    question = card["question"]
    assert question["id"]
    assert "answer" not in question

    first = asyncio.run(submit_answer(
        project_id, "learner", question_id=question["id"],
        answer="Energy is capacity to do work", confidence=4,
        hint_ladder=0, attempt_id="stable-attempt",
    ))
    retry = asyncio.run(submit_answer(
        project_id, "learner", question_id=question["id"],
        answer="different retry payload", confidence=1,
        hint_ladder=2, attempt_id="stable-attempt",
    ))
    assert retry == first

    with connect(project_id) as conn:
        raw_n = conn.execute(
            "SELECT COUNT(*) FROM attempts_raw WHERE user_id='learner'"
        ).fetchone()[0]
        tracked = conn.execute(
            "SELECT obs_n FROM bkt_params WHERE user_id='learner'"
        ).fetchone()[0]
        saved = json.loads(conn.execute(
            "SELECT result_json FROM agent_attempts WHERE attempt_id='stable-attempt'"
        ).fetchone()[0])
    assert raw_n == tracked == 1
    assert saved == first
    assert first["learning_update"]["sr"]["reps"] == 1


def test_review_without_due_cards_returns_empty_state(tmp_path, monkeypatch):
    project_id = "chat-review-empty"
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    ensure_schema(project_id)

    card = asyncio.run(create_question(project_id, "learner", mode="review"))

    assert card["status"] == "empty"
    assert card["question"] is None
    assert card["due_count"] == 0


def test_due_review_reopens_card_as_review_for_wiki_projection(tmp_path, monkeypatch):
    """A due card must be projected as review_completed when answered again."""
    project_id = "chat-review-projection"
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    ensure_dirs(project_id)

    practice = asyncio.run(create_question(project_id, "learner"))
    question = practice["question"]
    asyncio.run(submit_answer(
        project_id, "learner", question_id=question["question_id"], answer="A",
        confidence=4, hint_ladder=0, attempt_id="practice-attempt",
    ))
    with connect(project_id) as conn:
        conn.execute("UPDATE sr_schedule SET due_at=0")

    review = asyncio.run(create_question(project_id, "learner", mode="review"))
    assert review["question"]["question_id"] == question["question_id"]
    with connect(project_id) as conn:
        mode = conn.execute(
            "SELECT mode FROM agent_questions WHERE project_id=? AND user_id=? AND question_id=?",
            (project_id, "learner", question["question_id"]),
        ).fetchone()[0]
    assert mode == "review"

    asyncio.run(submit_answer(
        project_id, "learner", question_id=question["question_id"], answer="A",
        confidence=5, hint_ladder=0, attempt_id="review-attempt",
    ))
    with connect(project_id) as conn:
        event_types = [row[0] for row in conn.execute(
            "SELECT event_type FROM wiki_update_events WHERE project_id=? ORDER BY created_at",
            (project_id,),
        )]
    assert "review_completed" in event_types


def test_empty_wiki_fallback_is_objective_and_locally_gradable(tmp_path, monkeypatch):
    project_id = "chat-empty-fallback"
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    ensure_schema(project_id)

    card = asyncio.run(create_question(project_id, "learner"))
    question = card["question"]
    assert question["type"] == "multiple_choice"
    assert question["options"][0] == "先导入学习材料"

    result = asyncio.run(submit_answer(
        project_id, "learner", question_id=question["id"], answer="A",
        confidence=3, hint_ladder=0, attempt_id="empty-fallback-attempt",
    ))
    assert result["score"] == 1.0
    assert result["correct"] is True


def test_generated_teaching_pages_are_not_practice_material(tmp_path, monkeypatch):
    """A new project should prompt for material instead of quizzing its schema."""
    project_id = "chat-empty-with-taxonomy"
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    ensure_dirs(project_id)

    card = asyncio.run(create_question(project_id, "learner"))

    question = card["question"]
    assert question["options"][0] == "先导入学习材料"
    assert "TeachingObject" not in question["prompt"]


def test_chinese_short_answer_fallback_scores_exact_match(tmp_path, monkeypatch):
    project_id = "chat-short-answer-fallback"
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    ensure_schema(project_id)
    write_wiki_page(
        "concepts/definition.md",
        title="Definition",
        page_type="concept",
        content="# Definition\n\n核心定义是对概念本质的准确描述。",
        project_id=project_id,
    )

    async def fake_generate(req, project_id, existing_count, context, coverage=None):
        from models.tests import TestQuestion

        return [TestQuestion(
            id="generated-cn", type="short_answer", prompt="什么是核心定义？",
            answer="核心定义", explanation="核心定义描述概念本质。",
            related_page="concepts/definition.md", difficulty="basic",
        )]

    def fail_chat(*args, **kwargs):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr("routes.tests._generate_questions", fake_generate)
    monkeypatch.setattr("routes.tests.chat_complete", fail_chat)
    card = asyncio.run(create_question(project_id, "learner", page_path="concepts/definition.md"))
    question = card["question"]

    result = asyncio.run(submit_answer(
        project_id, "learner", question_id=question["id"],
        answer="核心定义", confidence=4, hint_ladder=0,
        attempt_id="cn-fallback-attempt",
    ))

    assert result["score"] == 1.0
    assert result["correct"] is True
