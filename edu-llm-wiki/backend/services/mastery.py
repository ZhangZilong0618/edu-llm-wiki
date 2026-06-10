"""Per-node mastery tracking for the learning graph.

A small finite state machine that moves nodes through five mastery levels
based on user attempts and exposures. State transitions are recorded in the
``graph_mastery`` SQLite table (see ``services.graph_store``).

States::

    new -> exposed -> learning -> proficient -> mastered

* ``new``        — never seen
* ``exposed``    — opened or read, no attempt yet
* ``learning``   — at least one attempt, score < pass_threshold
* ``proficient`` — score >= pass_threshold, retention still volatile
* ``mastered``   — score >= pass_threshold for ``stability_days`` days

The :func:`record_attempt` and :func:`record_exposure` helpers publish
``mastery.changed`` events on the in-process bus so the SSE endpoint can
push live updates to the graph view.
"""

from __future__ import annotations

import time
from typing import Any

from .graph_engine.events import publish  # local import to avoid cycle
from .graph_store import connect, execute

# Mastery FSM constants.
PASS_THRESHOLD = 0.7          # score >= 70% counts as a pass
STABILITY_DAYS = 14           # retain pass-score for two weeks to master
DECAY_DAYS = 30               # after this without exposure, decay one level

LEVEL_ORDER = ["new", "exposed", "learning", "proficient", "mastered"]


def _now() -> float:
    return time.time()


def _ensure_row(project_id: str, user_id: str, node_id: str) -> dict[str, Any]:
    """Read the current mastery row, inserting a default 'new' row if missing."""
    con = connect(project_id)
    try:
        row = con.execute(
            "SELECT * FROM graph_mastery WHERE user_id=? AND node_id=?",
            (user_id, node_id),
        ).fetchone()
        if row:
            return dict(row)
        now = _now()
        con.execute(
            """
            INSERT INTO graph_mastery
              (project_id, user_id, node_id, level, score, attempts, exposures,
               last_attempt_at, last_exposure_at, updated_at)
            VALUES (?, ?, ?, 'new', 0.0, 0, 0, NULL, NULL, ?)
            """,
            (project_id, user_id, node_id, now),
        )
        con.commit()
        return {
            "user_id": user_id,
            "node_id": node_id,
            "level": "new",
            "score": 0.0,
            "attempts": 0,
            "exposures": 0,
            "last_attempt_at": None,
            "last_exposure_at": None,
        }
    finally:
        con.close()


def _transition(prev: str, passed: bool, days_since_pass: float | None) -> str:
    """Compute the new mastery level from prior level + outcome."""
    if not passed:
        # failed attempt -> at least 'learning' if previously new/exposed
        return "learning" if prev in {"new", "exposed"} else prev

    # passed
    if prev == "mastered":
        return "mastered"
    if days_since_pass is not None and days_since_pass >= STABILITY_DAYS:
        return "mastered"
    return "proficient" if prev in {"proficient", "mastered"} else "proficient"


def record_attempt(
    *,
    project_id: str,
    user_id: str,
    node_id: str,
    score: float,
    max_score: float = 1.0,
) -> dict[str, Any]:
    """Record a graded attempt and update the mastery level."""
    row = _ensure_row(project_id, user_id, node_id)
    normalized = (score / max_score) if max_score > 0 else 0.0
    passed = normalized >= PASS_THRESHOLD
    now = _now()

    # Compute days since the last passing attempt (used by the FSM).
    days_since_pass: float | None = None
    if passed and row.get("last_attempt_at"):
        days_since_pass = (now - float(row["last_attempt_at"])) / 86_400

    new_level = _transition(row["level"], passed, days_since_pass)

    con = connect(project_id)
    try:
        execute(
            project_id,
            """
            UPDATE graph_mastery
               SET level = ?,
                   score = ?,
                   attempts = attempts + 1,
                   last_attempt_at = ?,
                   updated_at = ?
             WHERE user_id = ? AND node_id = ?
            """,
            (new_level, round(normalized, 3), now, now, user_id, node_id),
        )
    finally:
        con.close()

    if new_level != row["level"]:
        publish(
            project_id,
            "mastery.changed",
            {
                "user_id": user_id,
                "node_id": node_id,
                "from": row["level"],
                "to": new_level,
                "score": round(normalized, 3),
            },
        )

    return {
        "user_id": user_id,
        "node_id": node_id,
        "level": new_level,
        "score": round(normalized, 3),
        "attempts": row["attempts"] + 1,
        "exposures": row["exposures"],
        "passed": passed,
    }


def record_exposure(
    *,
    project_id: str,
    user_id: str,
    node_id: str,
) -> dict[str, Any]:
    """Record a passive exposure (page open, chat retrieval, etc.)."""
    row = _ensure_row(project_id, user_id, node_id)
    now = _now()

    # Decay check: long absence drops one level (but never below 'exposed').
    new_level = row["level"]
    last = row.get("last_exposure_at") or row.get("last_attempt_at")
    if last and row["level"] in {"proficient", "mastered"}:
        days = (now - float(last)) / 86_400
        if days > DECAY_DAYS:
            idx = max(0, LEVEL_ORDER.index(row["level"]) - 1)
            new_level = LEVEL_ORDER[idx]
    elif row["level"] == "new":
        new_level = "exposed"

    con = connect(project_id)
    try:
        execute(
            project_id,
            """
            UPDATE graph_mastery
               SET exposures = exposures + 1,
                   last_exposure_at = ?,
                   level = ?,
                   updated_at = ?
             WHERE user_id = ? AND node_id = ?
            """,
            (now, new_level, now, user_id, node_id),
        )
    finally:
        con.close()

    if new_level != row["level"]:
        publish(
            project_id,
            "mastery.changed",
            {
                "user_id": user_id,
                "node_id": node_id,
                "from": row["level"],
                "to": new_level,
            },
        )

    return {
        "user_id": user_id,
        "node_id": node_id,
        "level": new_level,
        "attempts": row["attempts"],
        "exposures": row["exposures"] + 1,
    }


def get_mastery(
    project_id: str,
    user_id: str,
    node_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return mastery rows for a user (optionally filtered to node_ids)."""
    con = connect(project_id)
    try:
        if node_ids:
            placeholders = ",".join("?" for _ in node_ids)
            rows = con.execute(
                f"""
                SELECT user_id, node_id, level, score, attempts, exposures,
                       last_attempt_at, last_exposure_at, updated_at
                  FROM graph_mastery
                 WHERE user_id = ? AND node_id IN ({placeholders})
                """,
                [user_id, *node_ids],
            ).fetchall()
        else:
            rows = con.execute(
                """
                SELECT user_id, node_id, level, score, attempts, exposures,
                       last_attempt_at, last_exposure_at, updated_at
                  FROM graph_mastery
                 WHERE user_id = ?
                """,
                (user_id,),
            ).fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


def mastery_summary(project_id: str, user_id: str) -> dict[str, int]:
    """Aggregate counts per mastery level for the dashboard."""
    con = connect(project_id)
    try:
        rows = con.execute(
            """
            SELECT level, COUNT(*) AS n
              FROM graph_mastery
             WHERE user_id = ?
             GROUP BY level
            """,
            (user_id,),
        ).fetchall()
    finally:
        con.close()
    out: dict[str, int] = {level: 0 for level in LEVEL_ORDER}
    for r in rows:
        out[r["level"]] = int(r["n"])
    out["total"] = sum(out.values())
    return out