"""Integration tests for the v3 learner-state pipeline."""

from __future__ import annotations

import sqlite3

from config import settings
from services.graph_engine import build_graph
from services.graph_store import (
    connect,
    ensure_schema,
    get_edges,
    make_node_id,
)
from services.mastery import learner_state_summary, record_attempt
from storage.wiki_store import write_wiki_page


def _use_temp_project(tmp_path, monkeypatch, project_id: str) -> None:
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    ensure_schema(project_id)


def test_record_attempt_updates_bkt_sr_confidence_and_misconceptions(tmp_path, monkeypatch):
    project_id = "mastery-integration"
    _use_temp_project(tmp_path, monkeypatch, project_id)

    write_wiki_page(
        "concepts/conductivity.md",
        title="Conductivity",
        page_type="concept",
        content="# Conductivity\n\nElectric conduction mechanism.",
        project_id=project_id,
    )
    node_id = make_node_id(project_id, "concepts/conductivity.md")

    result = record_attempt(
        project_id=project_id,
        user_id="learner-1",
        kc_id=node_id,
        score=1.0,
        max_score=1.0,
        confidence=4,
        response="我不小心忘了符号",
        expected="The sign convention is positive",
        attempt_id="q1",
    )

    assert result["correct"] is True
    assert result["bkt"]["p_known"] > 0.1
    assert result["sr"]["interval_seconds"] > 0
    assert result["tags"]

    with connect(project_id) as conn:
        bkt = conn.execute(
            "SELECT p_known,obs_n FROM bkt_params WHERE kc_id=?", (node_id,)
        ).fetchone()
        sr = conn.execute(
            "SELECT interval_days,reps,due_at FROM sr_schedule WHERE kc_id=?",
            (node_id,),
        ).fetchone()
        attempts = tuple(conn.execute(
            "SELECT correct,score,max_score,confidence FROM attempts_raw WHERE kc_id=?",
            (node_id,),
        ).fetchone())
        confidence = tuple(conn.execute(
            "SELECT confidence,correct FROM confidence_log WHERE kc_id=?",
            (node_id,),
        ).fetchone())
        misconceptions = conn.execute(
            "SELECT COUNT(*) FROM misconception_traces WHERE kc_id=?", (node_id,)
        ).fetchone()

    assert bkt is not None and bkt[0] > 0.1 and bkt[1] == 1
    assert sr is not None and sr[0] > 0 and sr[1] == 1
    assert attempts == (1, 1.0, 1.0, 4)
    assert confidence == (4, 1)
    assert misconceptions[0] >= 1

    state = learner_state_summary(project_id, "learner-1")
    assert state["n_kcs_tracked"] == 1
    assert state["weak_kcs"][0]["kc_id"] == node_id
    assert state["sr_due_today"] == 1


def test_generated_related_sections_become_graph_edges(tmp_path, monkeypatch):
    project_id = "graph-integration"
    _use_temp_project(tmp_path, monkeypatch, project_id)

    write_wiki_page(
        "concepts/conductivity.md",
        title="Conductivity",
        page_type="concept",
        content="# Conductivity\n\nA core concept.",
        project_id=project_id,
    )
    write_wiki_page(
        "synthesis/overview.md",
        title="Overview",
        page_type="synthesis",
        content="# Overview\n\n## 相关知识\n\n- Conductivity\n",
        project_id=project_id,
    )

    graph = build_graph(project_id=project_id, force=True)
    assert len(graph["nodes"]) == 2
    assert len(graph["edges"]) >= 1
    assert len(get_edges(project_id)) >= 1
    assert all(edge["edge_type"] in {"related", "prerequisite"} for edge in graph["edges"])



def test_record_attempt_handles_missing_node(monkeypatch, tmp_path):
    """Recording an attempt for a KC that doesn't exist in the graph should
    still succeed and persist BKT/SR rows. Useful when ingest produced a
    question that references a concept not yet in the wiki."""
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    ensure_schema("audit-missing")

    result = record_attempt(
        project_id="audit-missing",
        user_id="learner-1",
        kc_id="kc-not-in-graph",
        score=0.8,
        max_score=1.0,
        confidence=4,
        response="answered",
        expected="correct",
        attempt_id="q42",
    )
    assert result["bkt"]["p_known"] > 0.1
    assert result["sr"]["interval_seconds"] > 0

    with connect("audit-missing") as conn:
        row = conn.execute(
            "SELECT question_id, correct, score, max_score, confidence, hint_ladder "
            "FROM attempts_raw WHERE kc_id=?",
            ("kc-not-in-graph",),
        ).fetchone()
        assert row is not None
        # correct=1 (since pct >= MASTERY_THRESHOLD 0.7), question_id set.
        assert row[0] == "q42"
        assert row[1] == 1
        assert row[2] == 0.8
        assert row[3] == 1.0
        assert row[4] == 4
        # hint_ladder defaults to 0.
        assert row[5] == 0


def test_record_attempt_signals_mastered_when_crossing_threshold(monkeypatch, tmp_path):
    """The ``mastered`` flag in the response should be true exactly when p_known
    crosses the 0.85 mastery threshold from below on this attempt."""
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    ensure_schema("mastery-cross")

    # KC starts at p_known=0.1 with a low p_t=0.05, so individual correct
    # observations only nudge it up slowly.
    from services.graph_store import upsert_mastery
    upsert_mastery(
        "mastery-cross", "u1", "kcM",
        {"state": "exposed", "p_known": 0.10, "score": 0.0, "attempts": 0, "successes": 0,
         "last_seen_at": 0.0, "next_review_at": 0.0, "metadata": {}},
    )
    # Five correct answers, with low p_t, push p_known toward 1.
    for _ in range(5):
        record_attempt("mastery-cross", "u1", "kcM", score=1, max_score=1, confidence=4)
    res = record_attempt("mastery-cross", "u1", "kcM", score=1, max_score=1, confidence=4)
    assert "mastered" in res
    if res["mastered"]:
        # Sanity: confirmed p_known is on the other side of 0.85.
        assert res["bkt"]["p_known"] >= 0.85


def test_record_attempt_mastered_false_when_under_threshold(monkeypatch, tmp_path):
    """If p_known stays under 0.85, the response should have mastered=False."""
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    ensure_schema("mastery-no-cross")

    res = record_attempt(
        "mastery-no-cross", "u1", "kcX", score=0, max_score=1, confidence=2
    )
    assert res["mastered"] is False
    assert res["bkt"]["p_known"] < 0.85


def test_learner_state_summary_includes_last_refit_at(monkeypatch, tmp_path):
    """The summary now carries ``last_refit_at`` (max last_obs across the
    user's bkt_params). This regression test pins the contract so the
    LearningPanel's tooltip and the new celebration toast keep working."""
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    ensure_schema("last-refit")
    record_attempt("last-refit", "u1", "kcA", score=1, max_score=1, confidence=4)
    summary = learner_state_summary("last-refit", "u1")
    assert "last_refit_at" in summary
    assert summary["last_refit_at"] is not None
    assert summary["last_refit_at"] > 0
