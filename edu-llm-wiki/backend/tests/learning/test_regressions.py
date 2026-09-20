"""Regressions for defects that shipped bad state instead of raising.

Each case here corresponds to a bug that silently corrupted learner state
rather than one that failed loudly:

* BKT divided by P(correct) with no guard on the ``correct`` branch, so a
  learner starting from zero against a knowledge component with no guess
  rate raised ZeroDivisionError (``services/learning/bkt.py:observe``).
  A posterior outside [0, 1] was also written straight to SQLite, where it
  poisoned every later read.
* ``learner_state_summary`` fed ``_decay_risk`` the already-filtered
  due-today queue, making its numerator equal its denominator and pinning
  decay risk at 1.0 for any learner with a single due card
  (``services/mastery.py``).
"""
import time

import pytest

from config import settings
from services.graph_store import connect, ensure_schema
from services.learning.bkt import observe
from services.mastery import learner_state_summary


def test_bkt_observe_survives_zero_probability_correct():
    """p_known=0 together with p_g=0 makes P(correct)=0.

    Only the incorrect branch guarded that division, so a learner starting
    from zero against a non-guessing KC raised ZeroDivisionError.
    """
    # P(correct) == 0 here; the posterior collapses onto the learning rate.
    result = observe(p_known=0.0, p_t=0.2, p_g=0.0, p_s=0.1, correct=True)
    assert result[0] == pytest.approx(0.2)


def test_bkt_observe_never_leaves_unit_interval():
    """A p_known outside [0, 1] gets persisted and poisons every later read."""
    for p_known in (0.0, 0.5, 1.0):
        for p_g in (0.0, 0.2, 1.0):
            for p_s in (0.0, 0.1, 1.0):
                for correct in (True, False):
                    p_next, _, _, _ = observe(p_known, 0.2, p_g, p_s, correct)
                    assert 0.0 <= p_next <= 1.0


def test_decay_risk_spans_whole_sr_table_not_just_the_due_queue(monkeypatch, tmp_path):
    """Decay risk is a fraction of *mature* cards, not of due ones.

    ``learner_state_summary`` used to pass ``_sr_due_today(...)`` — rows
    already filtered to `due_at <= now + 24h` — into ``_decay_risk``. Every
    surviving row then satisfied the 14-day horizon test, so the ratio came
    back as 1.0 no matter how healthy the rest of the schedule was. With one
    overdue card among three mature ones the honest answer is 1/3.
    """
    project_id = "decay-risk"
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    ensure_schema(project_id)

    now = time.time()
    # Three mature cards (reps >= 3): one overdue, two comfortably scheduled
    # beyond the 14-day horizon.
    due_ats = (now - 10.0, now + 60 * 86_400.0, now + 90 * 86_400.0)
    with connect(project_id) as conn:
        for i, due_at in enumerate(due_ats):
            conn.execute(
                "INSERT OR REPLACE INTO sr_schedule("
                "project_id,user_id,kc_id,ef,interval_days,reps,quality_avg,"
                "due_at,last_review) VALUES(?,?,?,?,?,?,?,?,?)",
                (project_id, "u1", f"kc{i}", 2.5, 30, 4, 5.0, due_at, now),
            )

    state = learner_state_summary(project_id, "u1")
    assert state["sr_due_today"] == 1
    assert state["decay_risk"] == pytest.approx(1 / 3, abs=1e-3)
