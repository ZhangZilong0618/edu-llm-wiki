"""Regression tests for the learner-state summary aggregation."""

import asyncio

from services import mastery
from services.graph_store import connect, ensure_schema, make_node_id


def test_learner_state_summary_counts_attempts(monkeypatch, tmp_path):
    """Every record_attempt call must bump n_attempts by one.

    Regression for the bug where _bkt_rows() did not include obs_n and
    n_attempts always returned 0.
    """
    project_id = "test-project"
    user_id = "alice"
    kc_id = make_node_id(project_id, "concept/x.md")

    monkeypatch.setattr(mastery, "_connect", lambda pid: connect(pid))
    monkeypatch.setattr(mastery, "_now", lambda: 1700000000.0)
    monkeypatch.setattr(
        mastery,
        "_node_metadata",
        lambda pid: {kc_id: {"title": "X", "path": "concept/x.md"}},
    )

    # Bypass any global monkey-patching of projects_dir: ensure_schema needs
    # an isolated directory so it doesn't conflict with the default project.
    settings = __import__("config").settings
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))

    ensure_schema(project_id)
    with connect(project_id) as conn:
        conn.execute(
            """INSERT INTO bkt_params(project_id,user_id,kc_id,p_known,p_t,p_g,p_s,last_obs,obs_n)
               VALUES(?,?,?,0.5,0.2,0.2,0.1,1700000000.0,0)""",
            (project_id, user_id, kc_id),
        )
        conn.commit()

    # Three correct attempts should leave obs_n=3 and n_attempts=3.
    for _ in range(3):
        mastery.record_attempt(
            project_id=project_id,
            user_id=user_id,
            kc_id=kc_id,
            score=1.0,
            max_score=1.0,
            response="ok",
            expected="ok",
        )

    state = mastery.learner_state_summary(project_id=project_id, user_id=user_id)
    assert state["n_attempts"] == 3, state


def test_learner_state_summary_returns_zero_for_new_user(monkeypatch, tmp_path):
    """A fresh learner with no attempts must show 0, not crash."""
    project_id = "test-project"
    user_id = "bob"
    settings = __import__("config").settings
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))

    ensure_schema(project_id)

    state = mastery.learner_state_summary(project_id=project_id, user_id=user_id)
    assert state["n_attempts"] == 0
    assert state["n_kcs_tracked"] == 0
    assert state["p_known_avg"] == 0.0
