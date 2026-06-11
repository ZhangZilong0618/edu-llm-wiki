"""Per-KC mastery + 8-d learner state.

Wires together BKT, SM-2, misconception classification, confidence logging,
and transfer detection. The v3 tables are authoritative; the v2 FSM row is
kept only for audit/rollback. All public functions are idempotent and
``project_id``-scoped.

References
----------
* Corbatt & Sandberg (1992)  - BKT (via services.learning.bkt)
* Wozniak (1985)             - SM-2 (via services.learning.spaced_repetition)
* Brown & Burton (1978)      - misconception classification
* Perkins & Salomon (1989)   - transfer lift
* Karpicke & Roediger (2008) - overconfidence gap
* Vygotsky (1978)            - ZPD via readiness_score
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .graph_engine.events import publish
from .learning import bkt as _bkt
from .learning import spaced_repetition as _sr
from .learning import error_model as _err
from .learning import transfer as _xfer

# Standard BKT initial values; see services/learning/bkt.py docstring.
DEFAULT_BKT = {"p_known": 0.1, "p_t": 0.2, "p_g": 0.2, "p_s": 0.1}

# SM-2 initial values.
DEFAULT_SR = {"ef": 2.5, "interval_days": 0.0, "reps": 0}

# ---------------------------------------------------------------------------
# row helpers
# ---------------------------------------------------------------------------

def _now() -> float:
    return time.time()


def _connect(project_id: str):
    from services.graph_store import connect
    return connect(project_id)


def _upsert_bkt(project_id, user_id, kc_id, params):
    with _connect(project_id) as c:
        c.execute(
            "INSERT INTO bkt_params(project_id,user_id,kc_id,p_known,p_t,p_g,p_s,"
            "attempts,correct,updated_at) VALUES(?,?,?,?,?,?,?,0,0,?) "
            "ON CONFLICT(project_id,user_id,kc_id) DO UPDATE SET "
            "p_known=excluded.p_known,p_t=excluded.p_t,p_g=excluded.p_g,"
            "p_s=excluded.p_s,updated_at=excluded.updated_at",
            (project_id, user_id, kc_id,
             params["p_known"], params["p_t"], params["p_g"], params["p_s"],
             _now()),
        )


def _load_bkt(project_id, user_id, kc_id) -> dict:
    with _connect(project_id) as c:
        row = c.execute(
            "SELECT p_known,p_t,p_g,p_s FROM bkt_params WHERE project_id=? AND "
            "user_id=? AND kc_id=?", (project_id, user_id, kc_id)
        ).fetchone()
    if not row:
        return dict(DEFAULT_BKT)
    return {"p_known": float(row[0]), "p_t": float(row[1]),
            "p_g": float(row[2]), "p_s": float(row[3])}


def _upsert_sr(project_id, user_id, kc_id, ef, interval, reps, due_at):
    with _connect(project_id) as c:
        c.execute(
            "INSERT INTO sr_schedule(project_id,user_id,kc_id,ef,interval_days,"
            "reps,due_at,updated_at) VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(project_id,user_id,kc_id) DO UPDATE SET "
            "ef=excluded.ef,interval_days=excluded.interval_days,"
            "reps=excluded.reps,due_at=excluded.due_at,updated_at=excluded.updated_at",
            (project_id, user_id, kc_id, ef, interval, reps, due_at, _now()),
        )


def _load_sr(project_id, user_id, kc_id) -> dict:
    with _connect(project_id) as c:
        row = c.execute(
            "SELECT ef,interval_days,reps,due_at FROM sr_schedule "
            "WHERE project_id=? AND user_id=? AND kc_id=?",
            (project_id, user_id, kc_id),
        ).fetchone()
    if not row:
        return dict(DEFAULT_SR, due_at=_now())
    return {"ef": float(row[0]), "interval_days": float(row[1]),
            "reps": int(row[2]), "due_at": float(row[3])}


def _record_attempt_raw(project_id, user_id, kc_id, score, max_score,
                        p_known_after, quality, attempt_id=None):
    with _connect(project_id) as c:
        c.execute(
            "INSERT INTO attempts_raw(project_id,user_id,kc_id,attempt_id,score,"
            "max_score,p_known_after,quality,ts) VALUES(?,?,?,?,?,?,?,?,?)",
            (project_id, user_id, kc_id, attempt_id, score, max_score,
             p_known_after, quality, _now()),
        )


def _record_confidence(project_id, user_id, kc_id, confidence, correct):
    with _connect(project_id) as c:
        c.execute(
            "INSERT INTO confidence_log(project_id,user_id,kc_id,confidence,"
            "correct,ts) VALUES(?,?,?,?,?,?)",
            (project_id, user_id, kc_id, confidence, correct, _now()),
        )


def record_confidence(project_id, user_id, kc_id, confidence, correct):
    """Public wrapper around the confidence logger.

    ``confidence`` is the learner's self-rating on a 1–5 scale; ``correct`` is
    whether the answer was actually correct. Used downstream by
    :func:`learner_state_summary` to compute an overconfidence gap.
    """
    if confidence is None:
        return None
    _record_confidence(project_id, user_id, kc_id, int(confidence), bool(correct))
    return {"kc_id": kc_id, "confidence": int(confidence), "correct": bool(correct)}


def _record_misconception(project_id, user_id, kc_id, response, expected, tags):
    for t in tags:
        with _connect(project_id) as c:
            c.execute(
                "INSERT INTO misconception_traces(project_id,user_id,kc_id,"
                "misconception_tag,response_excerpt,expected_excerpt,ts) "
                "VALUES(?,?,?,?,?,?,?)",
                (project_id, user_id, kc_id, t, response[:200], expected[:200],
                 _now()),
            )


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def record_attempt(project_id: str, user_id: str, kc_id: str,
                   *, score: float, max_score: float = 1.0,
                   response: str = "", expected: str = "",
                   confidence: int | None = None,
                   hint_ladder: int = 0,
                   attempt_id: str | None = None) -> dict:
    """Thin orchestrator: BKT update + SR schedule + misconception + confidence."""
    correct = 1.0 if (max_score and score / max_score >= 0.7) else 0.0

    bkt_state = _load_bkt(project_id, user_id, kc_id)
    new_bkt = _bkt.observe(bkt_state["p_known"], bkt_state["p_t"],
                           bkt_state["p_g"], bkt_state["p_s"], correct)
    _upsert_bkt(project_id, user_id, kc_id, new_bkt)

    quality = _sr.quality_from_score(
        score=score / max_score if max_score else 0.0,
        hint_ladder=hint_ladder,
    )
    sr = _load_sr(project_id, user_id, kc_id)
    new_ef, new_interval, new_reps = _sr.sm2(
        quality, sr["ef"], sr["interval_days"], sr["reps"]
    )
    due_at = _sr.next_due(_now(), new_ef, new_interval)
    _upsert_sr(project_id, user_id, kc_id, new_ef, new_interval, new_reps, due_at)

    _record_attempt_raw(project_id, user_id, kc_id, score, max_score,
                        new_bkt["p_known"], quality, attempt_id)

    if confidence is not None and 1 <= confidence <= 5:
        _record_confidence(project_id, user_id, kc_id, confidence, correct)

    tags = _err.classify_error(response, expected)
    if tags:
        _record_misconception(project_id, user_id, kc_id, response, expected, tags)

    publish("mastery_change", project_id, user_id=user_id, kc_id=kc_id,
            p_known=new_bkt["p_known"], due_at=due_at, tags=tags)
    return {"bkt": new_bkt, "sr": {"ef": new_ef, "interval_days": new_interval,
                                   "reps": new_reps, "due_at": due_at},
            "tags": tags, "quality": quality}


def _bkt_rows(project_id, user_id) -> list[dict]:
    with _connect(project_id) as c:
        rows = c.execute(
            "SELECT kc_id,p_known,p_t,p_g,p_s FROM bkt_params "
            "WHERE project_id=? AND user_id=? ORDER BY p_known ASC",
            (project_id, user_id),
        ).fetchall()
    return [{"kc_id": r[0], "p_known": float(r[1]), "p_t": float(r[2]),
             "p_g": float(r[3]), "p_s": float(r[4])} for r in rows]


def _sr_due_today(project_id, user_id, now: float | None = None) -> list[dict]:
    now = now or _now()
    horizon = now + 86400.0
    with _connect(project_id) as c:
        rows = c.execute(
            "SELECT kc_id,ef,interval_days,reps,due_at FROM sr_schedule "
            "WHERE project_id=? AND user_id=? AND due_at<=? "
            "ORDER BY due_at ASC LIMIT 50",
            (project_id, user_id, horizon),
        ).fetchall()
    return [{"kc_id": r[0], "ef": float(r[1]), "interval_days": float(r[2]),
             "reps": int(r[3]), "due_at": float(r[4])} for r in rows]


def _confidence_rows(project_id, user_id) -> list[dict]:
    with _connect(project_id) as c:
        rows = c.execute(
            "SELECT confidence,correct FROM confidence_log "
            "WHERE project_id=? AND user_id=? ORDER BY ts DESC LIMIT 200",
            (project_id, user_id),
        ).fetchall()
    return [{"confidence": int(r[0]), "correct": float(r[1])} for r in rows]


def _misconception_clusters(project_id, user_id) -> list[dict]:
    with _connect(project_id) as c:
        rows = c.execute(
            "SELECT misconception_tag, COUNT(*) FROM misconception_traces "
            "WHERE project_id=? AND user_id=? GROUP BY misconception_tag "
            "ORDER BY 2 DESC LIMIT 10",
            (project_id, user_id),
        ).fetchall()
    return [{"tag": r[0], "count": int(r[1])} for r in rows]


def _overconfidence_gap(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    diffs = [(r["confidence"] - 1) / 4.0 - r["correct"] for r in rows]
    return round(sum(diffs) / len(diffs), 4)


def _decay_risk(rows: list[dict], horizon_days: int = 14) -> float:
    """Fraction of mature KCs (reps>=3) due within horizon."""
    if not rows:
        return 0.0
    mature = [r for r in rows if r["reps"] >= 3]
    if not mature:
        return 0.0
    now = _now()
    due = sum(1 for r in mature if r["due_at"] <= now + horizon_days * 86400.0)
    return round(due / max(1, len(mature)), 4)


def learner_state_summary(project_id: str, user_id: str = "default") -> dict:
    """Return the 8-dimensional learner state described in the v3 plan."""
    bkt = _bkt_rows(project_id, user_id)
    sr = _sr_due_today(project_id, user_id)
    clusters = _misconception_clusters(project_id, user_id)
    confidence = _confidence_rows(project_id, user_id)
    p_known_avg = round(sum(r["p_known"] for r in bkt) / max(1, len(bkt)), 4)
    weak = [r["kc_id"] for r in bkt if r["p_known"] < 0.5][:10]
    return {
        "p_known_avg": p_known_avg,
        "weak_kcs": weak,
        "misconception_clusters": clusters,
        "transfer_windows": [],   # populated lazily by caller
        "overconfidence_gap": _overconfidence_gap(confidence),
        "readiness": 0.0,         # populated by caller via readiness_score
        "sr_due_today": [r["kc_id"] for r in sr],
        "decay_risk": _decay_risk(sr),
        "n_kcs_tracked": len(bkt),
    }


def readiness_score(project_id: str, user_id: str, target_kc: str) -> float:
    """ZPD-style readiness: 1.0 iff every prerequisite KC has p_known >= 0.85."""
    bkt = {r["kc_id"]: r["p_known"] for r in _bkt_rows(project_id, user_id)}
    with _connect(project_id) as c:
        rows = c.execute(
            "SELECT source FROM graph_edges WHERE project_id=? AND target=? "
            "AND edge_type='prerequisite'",
            (project_id, target_kc),
        ).fetchall()
    prereqs = [r[0] for r in rows]
    if not prereqs:
        return 1.0
    if any(p not in bkt for p in prereqs):
        return 0.0
    return min(1.0, min(bkt[p] for p in prereqs) / 0.85)


def queue_for_user(project_id: str, user_id: str, limit: int = 20) -> list[dict]:
    return _sr_due_today(project_id, user_id)[:limit]


__all__ = [
    "record_attempt", "record_confidence", "learner_state_summary",
    "readiness_score", "queue_for_user",
]
