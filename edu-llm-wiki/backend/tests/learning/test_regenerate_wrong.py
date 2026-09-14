"""Integration test for the /regenerate-from-wrong test endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from config import settings
from routes.tests import _write_session
from models.tests import (
    TestAttempt,
    TestQuestion,
    TestSession,
    TestSummary,
)
from services.graph_store import ensure_schema
from storage.wiki_store import ensure_dirs


def _make_session(project_id: str, *, correct_count: int) -> TestSession:
    """Create a 4-question session with the first ``correct_count`` answered correctly."""
    questions = [
        TestQuestion(
            id=f"q{i}",
            type="multiple_choice",
            prompt=f"问题 {i}?",
            options=["A", "B", "C", "D"],
            answer="A" if i < 2 else "B",
            related_page="concepts/x.md",
            concepts=[],
            difficulty="basic",
        )
        for i in range(4)
    ]
    attempts = []
    for i, q in enumerate(questions):
        attempts.append(
            TestAttempt(
                question_id=q.id,
                user_answer=q.answer if i < correct_count else ("B" if q.answer == "A" else "A"),
                score=1.0 if i < correct_count else 0.0,
                max_score=1.0,
                level="good" if i < correct_count else "empty",
                feedback="",
                correct_answer=q.answer,
            )
        )
    return TestSession(
        id="sess-regen-test",
        title="原始测试",
        scope="wiki",
        source=None,
        mode="practice",
        difficulty="basic",
        status="submitted",
        questions=questions,
        attempts=attempts,
        score=float(correct_count),
        max_score=4.0,
        created_at="2026-01-01T00:00:00",
        submitted_at="2026-01-01T00:10:00",
    )


def test_regenerate_from_wrong_only_includes_wrong(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    ensure_schema("default")
    ensure_dirs(project_id="default")
    old = _make_session("default", correct_count=2)  # 2 correct, 2 wrong
    _write_session(old, "default")

    from main import app
    with TestClient(app) as client:
        r = client.post(
            "/api/tests/sess-regen-test/regenerate-from-wrong?project_id=default&user_id=u1"
        )
        assert r.status_code == 200, r.text
        new = TestSession.model_validate(r.json())
        assert new.id != old.id
        assert "重做错题" in (new.title or "")
        assert len(new.questions) == 2, f"expected 2 wrong, got {len(new.questions)}"
        # The two wrong questions (indices 2 and 3) should be the ones included.
        included_ids = {q.id for q in new.questions}
        assert included_ids == {"q2", "q3"}
        # Fresh session, no attempts.
        assert new.attempts == []
        assert new.status == "active"
        assert new.score is None


def test_regenerate_from_wrong_rejects_perfect_run(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    ensure_schema("default")
    ensure_dirs(project_id="default")
    perfect = _make_session("default", correct_count=4)  # all correct
    _write_session(perfect, "default")

    from main import app
    with TestClient(app) as client:
        r = client.post(
            "/api/tests/sess-regen-test/regenerate-from-wrong?project_id=default&user_id=u1"
        )
        assert r.status_code == 400
        assert "没有错题" in r.json()["detail"]


def test_submit_triggers_bkt_refit(monkeypatch, tmp_path):
    """Submitting a test should silently trigger a BKT refit so the
    LearningPanel's mastered count updates without a manual click."""
    from fastapi.testclient import TestClient
    from main import app
    from services.graph_store import ensure_schema, connect
    from storage.wiki_store import ensure_dirs
    from services.mastery import record_attempt

    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    ensure_schema("default")
    ensure_dirs(project_id="default")

    # Pre-load enough history so refit would succeed.
    for _ in range(6):
        record_attempt("default", "u1", "kc1", score=1, max_score=1, confidence=4)
        record_attempt("default", "u1", "kc2", score=0, max_score=1, confidence=2)

    # Write a test session.
    from routes.tests import _write_session
    from models.tests import TestSession, TestQuestion
    session = TestSession(
        id="sess-refit-on-submit",
        title="X",
        scope="wiki",
        source=None,
        mode="practice",
        difficulty="basic",
        status="active",
        questions=[TestQuestion(
            id="q1", type="multiple_choice",
            prompt="x?", options=["A","B","C","D"], answer="A",
            related_page="concepts/x.md", concepts=[], difficulty="basic",
        )],
        attempts=[], score=None, max_score=None,
        created_at="2026-01-01T00:00:00", submitted_at=None,
    )
    _write_session(session, "default")

    with TestClient(app) as client:
        r = client.post(
            "/api/tests/sess-refit-on-submit/submit?project_id=default&user_id=u1",
            json={"answers": {"q1": "A"}, "confidences": {"q1": 4}},
        )
        assert r.status_code == 200

    # After submit, attempts_raw should have new entry.
    with connect("default") as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM attempts_raw WHERE project_id=? AND user_id=? AND question_id='q1'",
            ("default", "u1"),
        ).fetchone()
        assert n[0] == 1
        # And bkt_params has at least one row (refit wrote them).
        n_bkt = conn.execute(
            "SELECT COUNT(*) FROM bkt_params WHERE project_id=? AND user_id=?",
            ("default", "u1"),
        ).fetchone()
        assert n_bkt[0] >= 1
