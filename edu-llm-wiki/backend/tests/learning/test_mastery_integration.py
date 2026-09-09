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

