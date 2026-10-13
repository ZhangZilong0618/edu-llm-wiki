"""End-to-end learning scenarios over imported Wiki material.

These tests model the path a learner takes in the product instead of testing
the BKT/SM-2 observers in isolation:

* import a small source document into a project;
* read it and ask a normal question;
* ask the conversational agent for a card, answer it, and inspect mastery;
* let the card become due, review it, and inspect the Wiki projection.

The LLM boundaries are stubbed so the scenarios remain deterministic while
the real ingest, question ledger, mastery observers, and Markdown projector
run together.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from config import settings
from models.tests import TestQuestion as QuestionModel
from services.agent_assessment import create_question, submit_answer
from services.graph_store import close_all, connect, ensure_schema
from services.wiki_auto_update import record_dialogue, record_learning_event
from storage.wiki_store import ensure_dirs, write_wiki_page


def _project(tmp_path, monkeypatch, project_id: str) -> Path:
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    close_all()
    ensure_schema(project_id)
    ensure_dirs(project_id=project_id)
    return Path(tmp_path) / project_id


def _stub_import(monkeypatch, page_title: str = "元素") -> None:
    """Make ingest deterministic while preserving its real write/graph path."""
    from services import ingest_engine, relation_extraction

    async def fake_extract(*_args, **_kwargs):
        return {
            "concepts": [{
                "name": page_title,
                "definition": "元素是具有相同核电荷数的一类原子的总称。",
                "related_concepts": [],
                "prerequisites": [],
            }],
            "facts": [],
            "formulas": [],
            "principles": [],
        }

    async def fake_relations(*_args, **_kwargs):
        return {"relations": []}

    async def fake_pages(_plan, *, project_id, source_relative_path, emit=None):
        return [{
            "path": "concepts/elements.md",
            "title": page_title,
            "page_type": "concept",
            "content": (
                f"# {page_title}\n\n## 定义\n\n"
                "元素是具有相同核电荷数的一类原子的总称。\n"
            ),
            "sources": [source_relative_path],
            "tags": ["chemistry"],
            "prerequisites": [],
            "related": [],
        }]

    monkeypatch.setattr(ingest_engine, "extract_knowledge_units", fake_extract)
    monkeypatch.setattr(ingest_engine, "_generate_core_pages", fake_pages)
    monkeypatch.setattr(relation_extraction, "run_relation_extraction", fake_relations)


def test_imported_material_is_used_by_normal_dialogue_projection(tmp_path, monkeypatch):
    """A normal ask/read turn updates the imported page and activity ledger."""
    project_id = "scenario-dialogue"
    root = _project(tmp_path, monkeypatch, project_id)
    _stub_import(monkeypatch)

    source = root / "sources" / "chemistry.md"
    source.write_text("# 元素\n\n元素按核电荷数定义。", encoding="utf-8")

    from services.ingest_engine import run_ingest

    result = asyncio.run(run_ingest("chemistry.md", project_id=project_id))
    assert result["status"] == "generated"
    assert "concepts/elements.md" in result["wiki_pages_created"]

    # Simulate the learner opening the imported page and then asking a normal
    # question. The raw transcript stays out of Markdown; only safe summaries
    # and the cited page are projected.
    record_learning_event(
        project_id,
        "simulated-learner",
        event_kind="analysisView",
        related_page="concepts/elements.md",
        mode="wiki",
        event_id="read-elements-1",
    )
    dialogue = record_dialogue(
        project_id,
        "simulated-learner",
        query="元素是如何定义的？",
        response="元素是具有相同核电荷数的一类原子的总称。",
        conversation_id="simulated-chat",
        cited_pages=[{"path": "concepts/elements.md", "title": "元素"}],
        event_id="ask-elements-1",
    )
    assert dialogue["status"] == "updated"

    page = (root / "wiki" / "concepts" / "elements.md").read_text(encoding="utf-8")
    activity = list((root / "wiki" / "learning" / "activity").glob("*.md"))
    assert "元素是具有相同核电荷数的一类原子的总称" in page
    assert "学习活动（自动汇总）" in page
    assert "对话涉及" in page
    assert "学习语义快照" in page
    assert "关联知识页: `concepts/elements.md`" in page
    assert "最近事件: dialogue_completed（对话学习）" in page
    assert activity and "对话完成" in activity[0].read_text(encoding="utf-8")
    with connect(project_id) as conn:
        event_types = {row[0] for row in conn.execute(
            "SELECT event_type FROM wiki_update_events WHERE project_id=?",
            (project_id,),
        )}
    assert {"learning_event", "dialogue_completed"} <= event_types


def test_simulated_learner_practice_and_review_update_mastery_and_pages(
    tmp_path, monkeypatch,
):
    """Wrong answer -> BKT/SM-2 -> due review -> TeachingObject projections."""
    project_id = "scenario-practice-review"
    root = _project(tmp_path, monkeypatch, project_id)
    write_wiki_page(
        "concepts/elements.md",
        "元素",
        "concept",
        "# 元素\n\n元素是具有相同核电荷数的一类原子的总称。",
        project_id=project_id,
    )

    async def fake_generate(req, project_id, existing_count, context, coverage=None):
        assert "元素" in context
        return [QuestionModel(
            id="generated-elements",
            type="multiple_choice",
            prompt="元素的定义依据是什么？",
            options=["核电荷数", "物理体积"],
            answer="A",
            explanation="元素按原子的核电荷数定义。",
            related_page="concepts/elements.md",
            concepts=["元素"],
            difficulty="basic",
        )]

    monkeypatch.setattr("routes.tests._generate_questions", fake_generate)

    card = asyncio.run(create_question(
        project_id,
        "simulated-learner",
        mode="practice",
        page_path="concepts/elements.md",
    ))
    question = card["question"]
    assert question["related_page"] == "concepts/elements.md"
    assert "answer" not in question  # the client never receives the key

    # Deliberately choose the distractor and report low confidence. This
    # exercises the same local grader the chat endpoint uses.
    wrong = asyncio.run(submit_answer(
        project_id,
        "simulated-learner",
        question_id=question["question_id"],
        answer="B",
        confidence=1,
        hint_ladder=1,
        attempt_id="simulated-practice-1",
    ))
    assert wrong["correct"] is False
    assert 0 <= wrong["learning_update"]["bkt"]["p_known"] <= 1
    # SM-2 resets repetitions after a failed observation; the first due card
    # is nevertheless persisted and can be reopened for review.
    assert wrong["learning_update"]["sr"]["reps"] == 0

    with connect(project_id) as conn:
        bkt = conn.execute(
            "SELECT p_known,obs_n FROM bkt_params WHERE user_id=?",
            ("simulated-learner",),
        ).fetchone()
        sr = conn.execute(
            "SELECT reps,due_at FROM sr_schedule WHERE user_id=?",
            ("simulated-learner",),
        ).fetchone()
        events = [row[0] for row in conn.execute(
            "SELECT event_type FROM wiki_update_events WHERE project_id=?",
            (project_id,),
        )]
    assert bkt is not None and bkt[1] == 1
    assert sr is not None and sr[0] == 0
    assert {"question_issued", "assessment_attempt", "mastery_change"} <= set(events)

    # Make the first card due, then ask for a review. The review must reopen
    # the same server-owned question and be projected as a distinct event.
    with connect(project_id) as conn:
        conn.execute(
            "UPDATE sr_schedule SET due_at=0 WHERE user_id=?",
            ("simulated-learner",),
        )
    review = asyncio.run(create_question(
        project_id, "simulated-learner", mode="review",
    ))
    assert review["question"]["question_id"] == question["question_id"]
    reviewed = asyncio.run(submit_answer(
        project_id,
        "simulated-learner",
        question_id=question["question_id"],
        answer="A",
        confidence=5,
        hint_ladder=0,
        attempt_id="simulated-review-1",
    ))
    assert reviewed["correct"] is True
    assert reviewed["learning_update"]["sr"]["reps"] == 1

    wiki = root / "wiki"
    related = (wiki / "concepts" / "elements.md").read_text(encoding="utf-8")
    assessment = (wiki / "teaching" / "assessment" / "AssessmentResult.md").read_text(encoding="utf-8")
    learning_state = (wiki / "teaching" / "mastery-tracking" / "LearningState.md").read_text(encoding="utf-8")
    activity = "\n".join(p.read_text(encoding="utf-8") for p in (wiki / "learning" / "activity").glob("*.md"))
    assert "题目发放" in related
    assert "练习反馈" in related
    assert "练习反馈" in assessment
    assert "学习语义快照" in assessment
    assert "知识点标识:" in assessment
    assert "BKT 掌握度:" in assessment
    assert "SM-2 下次复习:" in assessment
    assert "最近得分:" in assessment
    assert "BKT 掌握度:" in learning_state
    assert "复习完成" in activity
    # TeachingObject pages expose an aggregate learning insight in addition
    # to the audit lines, so a reviewer can see what changed without opening
    # the private event ledger.
    assert "学习洞察" in related
    assert "关联事件:" in related
    assert "学习洞察" in assessment
    assert "关联事件:" in assessment
    assert "学习洞察" in learning_state
    assert "关联事件:" in learning_state

    with connect(project_id) as conn:
        event_types = {row[0] for row in conn.execute(
            "SELECT event_type FROM wiki_update_events WHERE project_id=?",
            (project_id,),
        )}
        attempt_count = conn.execute(
            "SELECT COUNT(*) FROM attempts_raw WHERE user_id=?",
            ("simulated-learner",),
        ).fetchone()[0]
    assert "review_completed" in event_types
    assert attempt_count == 2


def test_two_simulated_learners_keep_mastery_and_snapshots_separate(tmp_path, monkeypatch):
    """A shared imported page can serve users without mixing learner state."""
    project_id = "scenario-two-learners"
    root = _project(tmp_path, monkeypatch, project_id)
    write_wiki_page(
        "concepts/elements.md", "元素", "concept",
        "# 元素\n\n元素按核电荷数定义。", project_id=project_id,
    )

    from services.mastery import record_attempt

    record_attempt(project_id, "alice", "kc-elements", score=1, max_score=1, confidence=5)
    record_attempt(project_id, "bob", "kc-elements", score=0, max_score=1, confidence=1)

    with connect(project_id) as conn:
        rows = conn.execute(
            "SELECT user_id,p_known,obs_n FROM bkt_params WHERE kc_id=? ORDER BY user_id",
            ("kc-elements",),
        ).fetchall()
    assert [row[0] for row in rows] == ["alice", "bob"]
    assert rows[0][1] != rows[1][1]
    assert all(row[2] == 1 for row in rows)

    learners = list((root / "wiki" / "learning" / "learners").glob("u_*.md"))
    assert len(learners) == 2
    snapshots = [json.loads(
        text.split("```json", 1)[1].split("```", 1)[0]
    )["p_known"] for path in learners
        if (text := path.read_text(encoding="utf-8")) and "```json" in text]
    assert len(snapshots) == 2
    assert len(set(snapshots)) == 2
