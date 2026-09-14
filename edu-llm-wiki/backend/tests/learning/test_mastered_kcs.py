"""Regression test for the mastered_kcs field on the learner state summary."""

from services import mastery
from services.graph_store import connect, ensure_schema, make_node_id


def test_mastered_kcs_lists_kcs_above_threshold(monkeypatch, tmp_path):
    project_id = "test-project"
    user_id = "alice"
    settings = __import__("config").settings
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    monkeypatch.setattr(mastery, "_connect", lambda pid: connect(pid))
    monkeypatch.setattr(mastery, "_now", lambda: 1700000000.0)
    monkeypatch.setattr(
        mastery,
        "_node_metadata",
        lambda pid: {
            make_node_id(pid, "x.md"): {"title": "X", "path": "x.md"},
            make_node_id(pid, "y.md"): {"title": "Y", "path": "y.md"},
        },
    )

    ensure_schema(project_id)
    state = mastery.learner_state_summary(project_id=project_id, user_id=user_id)
    # No attempts yet: neither list is populated.
    assert state["weak_kcs"] == []
    assert state["mastered_kcs"] == []

    kc_x = make_node_id(project_id, "x.md")
    kc_y = make_node_id(project_id, "y.md")

    # Seed BKT rows directly so we can control p_known deterministically.
    with connect(project_id) as conn:
        conn.executemany(
            """INSERT INTO bkt_params(project_id,user_id,kc_id,p_known,p_t,p_g,p_s,last_obs,obs_n)
               VALUES(?,?,?,?,0.2,0.2,0.1,?,1)""",
            [
                (project_id, user_id, kc_x, 0.90, 1700000000.0),
                (project_id, user_id, kc_y, 0.40, 1700000000.0),
            ],
        )
        conn.commit()

    state = mastery.learner_state_summary(project_id=project_id, user_id=user_id)
    assert len(state["mastered_kcs"]) == 1, state
    assert state["mastered_kcs"][0]["kc_id"] == kc_x
    assert state["mastered_kcs"][0]["p_known"] == 0.90
    assert state["weak_kcs"][0]["kc_id"] == kc_y
    assert state["n_kcs_mastered"] == 1
    assert state["n_kcs_tracked"] == 2
