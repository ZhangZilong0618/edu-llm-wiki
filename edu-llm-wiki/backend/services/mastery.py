"""Per-KC mastery and the eight-dimensional learner state.

This module is the integration layer for the pedagogical observers:

* BKT posterior update (Corbett & Anderson / Corbett & Sandberg)
* SM-2 spaced repetition (Wozniak)
* misconception classification (Brown & Burton)
* confidence calibration (Karpicke & Roediger)
* prerequisite readiness (Vygotsky's ZPD)
* adjacent transfer windows (Perkins & Salomon)

The v3 SQLite tables are authoritative. The older ``node_mastery`` row is
updated as an audit/rollback record, but BKT and SM-2 state are read from the
v3 tables.
"""

from __future__ import annotations

import time

from .graph_engine.events import publish
from .learning import bkt as _bkt
from .learning import error_model as _err
from .learning import spaced_repetition as _sr
from .graph_store import (
    connect,
    get_edges,
    get_nodes,
    record_attempt as store_record_attempt,
    record_event,
)

DEFAULT_BKT = {"p_known": 0.1, "p_t": 0.2, "p_g": 0.2, "p_s": 0.1}
DEFAULT_SR = {"ef": 2.5, "interval_seconds": 0.0, "reps": 0}
MASTERY_THRESHOLD = 0.7
READINESS_THRESHOLD = 0.85


def _now() -> float:
    return time.time()


def _connect(project_id: str):
    return connect(project_id)


def _node_metadata(project_id: str) -> dict[str, dict[str, str]]:
    """Return node metadata keyed by the stable graph node id."""
    out: dict[str, dict[str, str]] = {}
    for node in get_nodes(project_id):
        out[node["id"]] = {
            "title": node.get("label") or node.get("title") or node["id"],
            "path": node.get("page_path") or node.get("metadata", {}).get("path", ""),
        }
    return out


def _upsert_bkt(conn, project_id: str, user_id: str, kc_id: str, params: dict) -> None:
    conn.execute(
        """
        INSERT INTO bkt_params(
            project_id,user_id,kc_id,p_known,p_t,p_g,p_s,last_obs,obs_n
        ) VALUES(?,?,?,?,?,?,?,?,1)
        ON CONFLICT(project_id,user_id,kc_id) DO UPDATE SET
            p_known=excluded.p_known,
            p_t=excluded.p_t,
            p_g=excluded.p_g,
            p_s=excluded.p_s,
            last_obs=excluded.last_obs,
            obs_n=bkt_params.obs_n+1
        """,
        (
            project_id, user_id, kc_id,
            params["p_known"], params["p_t"], params["p_g"], params["p_s"],
            _now(),
        ),
    )


def _load_bkt(project_id: str, user_id: str, kc_id: str) -> dict:
    with _connect(project_id) as conn:
        row = conn.execute(
            """
            SELECT p_known,p_t,p_g,p_s
            FROM bkt_params
            WHERE project_id=? AND user_id=? AND kc_id=?
            """,
            (project_id, user_id, kc_id),
        ).fetchone()
    if not row:
        return dict(DEFAULT_BKT)
    return {
        "p_known": float(row[0]),
        "p_t": float(row[1]),
        "p_g": float(row[2]),
        "p_s": float(row[3]),
    }


def _upsert_sr(
    conn,
    project_id: str,
    user_id: str,
    kc_id: str,
    ef: float,
    interval_seconds: float,
    reps: int,
    due_at: float,
    quality: int,
) -> None:
    interval_days = interval_seconds / 86400.0
    conn.execute(
        """
        INSERT INTO sr_schedule(
            project_id,user_id,kc_id,ef,interval_days,reps,quality_avg,due_at,last_review
        ) VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(project_id,user_id,kc_id) DO UPDATE SET
            ef=excluded.ef,
            interval_days=excluded.interval_days,
            reps=excluded.reps,
            quality_avg=excluded.quality_avg,
            due_at=excluded.due_at,
            last_review=excluded.last_review
        """,
        (
            project_id, user_id, kc_id, ef, interval_days, reps,
            float(quality), due_at, _now(),
        ),
    )


def _load_sr(project_id: str, user_id: str, kc_id: str) -> dict:
    with _connect(project_id) as conn:
        row = conn.execute(
            """
            SELECT ef,interval_days,reps
            FROM sr_schedule
            WHERE project_id=? AND user_id=? AND kc_id=?
            """,
            (project_id, user_id, kc_id),
        ).fetchone()
    if not row:
        return dict(DEFAULT_SR, due_at=_now())
    return {
        "ef": float(row[0]),
        "interval_seconds": float(row[1]) * 86400.0,
        "reps": int(row[2]),
    }


def _record_attempt_raw(
    conn,
    project_id: str,
    user_id: str,
    kc_id: str,
    score: float,
    max_score: float,
    correct: bool,
    confidence: int | None,
    hint_ladder: int,
    question_id: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO attempts_raw(
            project_id,user_id,kc_id,question_id,correct,score,max_score,
            confidence,latency_ms,hint_ladder,ts
        ) VALUES(?,?,?,?,?,?,?,?,NULL,?,?)
        """,
        (
            project_id, user_id, kc_id, question_id,
            int(correct), score, max_score,
            confidence, hint_ladder, _now(),
        ),
    )


def _record_confidence(
    conn,
    project_id: str,
    user_id: str,
    kc_id: str,
    confidence: int,
    correct: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO confidence_log(
            project_id,user_id,kc_id,confidence,correct,residual,ts
        ) VALUES(?,?,?,?,?,?,?)
        """,
        (
            project_id, user_id, kc_id, confidence, int(correct),
            (confidence / 5.0) - float(correct), _now(),
        ),
    )


def _record_misconception(
    conn,
    project_id: str,
    user_id: str,
    kc_id: str,
    response: str,
    expected: str,
    tags: list[str],
    question_id: str | None,
) -> None:
    for tag in tags:
        conn.execute(
            """
            INSERT INTO misconception_traces(
                project_id,user_id,kc_id,misconception_tag,response_text,
                matched_pattern,question_id,created_at
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                project_id, user_id, kc_id, tag,
                response[:200], expected[:200], question_id, _now(),
            ),
        )


def record_confidence(
    project_id: str,
    user_id: str,
    kc_id: str,
    confidence: int | None,
    correct: bool,
) -> dict | None:
    """Record a standalone confidence self-rating."""
    if confidence is None:
        return None
    confidence = int(confidence)
    if not 1 <= confidence <= 5:
        return None
    with _connect(project_id) as conn:
        _record_confidence(conn, project_id, user_id, kc_id, confidence, correct)
    return {"kc_id": kc_id, "confidence": confidence, "correct": bool(correct)}


def record_attempt(
    project_id: str,
    user_id: str,
    kc_id: str,
    *,
    score: float,
    max_score: float = 1.0,
    response: str = "",
    expected: str = "",
    confidence: int | None = None,
    hint_ladder: int = 0,
    attempt_id: str | None = None,
) -> dict:
    """Apply one attempt through BKT, SM-2, confidence, and misconception observers."""
    if max_score <= 0:
        max_score = 1.0
    score = max(0.0, min(float(score), float(max_score)))
    pct = score / max_score
    correct = pct >= MASTERY_THRESHOLD
    confidence = int(confidence) if confidence is not None else None
    if confidence is not None:
        confidence = max(1, min(5, confidence))

    bkt_prior = _load_bkt(project_id, user_id, kc_id)
    p_known, p_t, p_g, p_s = _bkt.observe(
        bkt_prior["p_known"], bkt_prior["p_t"],
        bkt_prior["p_g"], bkt_prior["p_s"], correct,
    )
    bkt_next = {
        "p_known": p_known, "p_t": p_t, "p_g": p_g, "p_s": p_s,
    }

    quality = _sr.quality_from_score(
        score=score,
        max_score=max_score,
        hint_ladder=hint_ladder,
    )
    sr_prior = _load_sr(project_id, user_id, kc_id)
    sr_next = _sr.sm2(
        quality,
        sr_prior["ef"],
        sr_prior["interval_seconds"],
        sr_prior["reps"],
    )
    due_at = _sr.next_due(_now(), sr_next.interval_seconds)
    tags = _err.classify_error(response, expected)

    with _connect(project_id) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _upsert_bkt(conn, project_id, user_id, kc_id, bkt_next)
            _upsert_sr(
                conn, project_id, user_id, kc_id,
                sr_next.ease_factor,
                sr_next.interval_seconds,
                sr_next.repetitions,
                due_at,
                quality,
            )
            _record_attempt_raw(
                conn, project_id, user_id, kc_id,
                score, max_score, correct, confidence,
                hint_ladder, attempt_id,
            )
            if confidence is not None:
                _record_confidence(conn, project_id, user_id, kc_id, confidence, correct)
            if tags:
                _record_misconception(
                    conn, project_id, user_id, kc_id,
                    response, expected, tags, attempt_id,
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    # Keep the legacy graph-view mastery row in sync for audit and rollback.
    try:
        store_record_attempt(
            project_id=project_id,
            user_id=user_id,
            node_id=kc_id,
            score=score,
            max_score=max_score,
            correct=correct,
        )
    except Exception:
        # The v3 tables remain authoritative if this legacy write fails.
        pass

    payload = {
        "user_id": user_id,
        "kc_id": kc_id,
        "p_known": bkt_next["p_known"],
        "due_at": due_at,
        "tags": tags,
    }
    try:
        record_event(project_id, "mastery_change", payload)
    except Exception:
        pass
    publish("mastery_change", project_id, **payload)

    return {
        "bkt": bkt_next,
        "sr": {
            "ef": sr_next.ease_factor,
            "interval_seconds": sr_next.interval_seconds,
            "reps": sr_next.repetitions,
            "due_at": due_at,
        },
        "tags": tags,
        "quality": quality,
        "correct": correct,
    }


def _bkt_rows(project_id: str, user_id: str) -> list[dict]:
    with _connect(project_id) as conn:
        rows = conn.execute(
            """
            SELECT kc_id,p_known,p_t,p_g,p_s
            FROM bkt_params
            WHERE project_id=? AND user_id=?
            ORDER BY p_known ASC
            """,
            (project_id, user_id),
        ).fetchall()
    return [
        {
            "kc_id": r[0], "p_known": float(r[1]),
            "p_t": float(r[2]), "p_g": float(r[3]), "p_s": float(r[4]),
        }
        for r in rows
    ]


def _sr_due_today(project_id: str, user_id: str, now: float | None = None) -> list[dict]:
    now = now or _now()
    horizon = now + 86400.0
    with _connect(project_id) as conn:
        rows = conn.execute(
            """
            SELECT kc_id,ef,interval_days,reps,due_at
            FROM sr_schedule
            WHERE project_id=? AND user_id=? AND due_at<=?
            ORDER BY due_at ASC LIMIT 100
            """,
            (project_id, user_id, horizon),
        ).fetchall()
    return [
        {
            "kc_id": r[0], "ef": float(r[1]),
            "interval_seconds": float(r[2]) * 86400.0,
            "reps": int(r[3]), "due_at": float(r[4]),
        }
        for r in rows
    ]


def _confidence_rows(project_id: str, user_id: str) -> list[dict]:
    with _connect(project_id) as conn:
        rows = conn.execute(
            """
            SELECT confidence,correct
            FROM confidence_log
            WHERE project_id=? AND user_id=?
            ORDER BY ts DESC LIMIT 200
            """,
            (project_id, user_id),
        ).fetchall()
    return [{"confidence": int(r[0]), "correct": float(r[1])} for r in rows]


def _misconception_clusters(project_id: str, user_id: str) -> list[dict]:
    with _connect(project_id) as conn:
        rows = conn.execute(
            """
            SELECT misconception_tag,COUNT(*)
            FROM misconception_traces
            WHERE project_id=? AND user_id=?
            GROUP BY misconception_tag
            ORDER BY 2 DESC LIMIT 10
            """,
            (project_id, user_id),
        ).fetchall()
    return [
        {"tag": r[0], "label": r[0].replace("_", " "), "count": int(r[1])}
        for r in rows
    ]


def _overconfidence_gap(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    diffs = [(r["confidence"] - 1) / 4.0 - r["correct"] for r in rows]
    return round(sum(diffs) / len(diffs), 4)


def _decay_risk(rows: list[dict], horizon_days: int = 14) -> float:
    if not rows:
        return 0.0
    mature = [r for r in rows if r["reps"] >= 3]
    if not mature:
        return 0.0
    now = _now()
    due = sum(1 for r in mature if r["due_at"] <= now + horizon_days * 86400.0)
    return round(due / len(mature), 4)


def _transfer_windows(project_id: str, bkt_rows: list[dict]) -> list[dict]:
    """Return graph-adjacent transfer opportunities.

    This is intentionally a recommendation signal, not a causal claim: A is
    sufficiently mastered and B is insufficiently mastered while the graph says
    they are adjacent.
    """
    mastery = {r["kc_id"]: r["p_known"] for r in bkt_rows}
    windows: list[dict] = []
    for edge in get_edges(project_id):
        src = edge["source"]
        dst = edge["target"]
        if mastery.get(src, 0.0) >= 0.85 and 0.0 < mastery.get(dst, 0.0) < 0.3:
            windows.append({"from": src, "to": dst})
        elif mastery.get(dst, 0.0) >= 0.85 and 0.0 < mastery.get(src, 0.0) < 0.3:
            windows.append({"from": dst, "to": src})
    return windows[:10]


def _readiness_summary(project_id: str, bkt_rows: list[dict]) -> float:
    mastery = {r["kc_id"]: r["p_known"] for r in bkt_rows}
    prereqs_by_target: dict[str, list[str]] = {}
    for edge in get_edges(project_id):
        if edge.get("edge_type") != "prerequisite":
            continue
        prereqs_by_target.setdefault(edge["target"], []).append(edge["source"])
    if not prereqs_by_target:
        return 1.0
    scores: list[float] = []
    for prereqs in prereqs_by_target.values():
        if any(p not in mastery for p in prereqs):
            scores.append(0.0)
        else:
            scores.append(min(1.0, min(mastery[p] for p in prereqs) / READINESS_THRESHOLD))
    return round(sum(scores) / len(scores), 4)


def learner_state_summary(project_id: str, user_id: str = "default") -> dict:
    """Return the learner-facing eight-dimensional state."""
    bkt = _bkt_rows(project_id, user_id)
    sr = _sr_due_today(project_id, user_id)
    clusters = _misconception_clusters(project_id, user_id)
    confidence = _confidence_rows(project_id, user_id)
    metadata = _node_metadata(project_id)

    weak = [
        {
            "kc_id": r["kc_id"],
            "title": metadata.get(r["kc_id"], {}).get("title", r["kc_id"]),
            "path": metadata.get(r["kc_id"], {}).get("path", ""),
            "p_known": r["p_known"],
        }
        for r in bkt if r["p_known"] < 0.5
    ]
    weak.sort(key=lambda r: r["p_known"])

    return {
        "p_known_avg": round(sum(r["p_known"] for r in bkt) / max(1, len(bkt)), 4),
        "weak_kcs": weak[:10],
        "misconception_clusters": clusters,
        "transfer_windows": _transfer_windows(project_id, bkt),
        "overconfidence_gap": _overconfidence_gap(confidence),
        "readiness": _readiness_summary(project_id, bkt),
        "sr_due_today": len(sr),
        "decay_risk": _decay_risk(sr),
        "n_kcs_tracked": len(bkt),
    }


def readiness_score(project_id: str, user_id: str, target_kc: str) -> float:
    """ZPD-style readiness for one target KC."""
    bkt = {r["kc_id"]: r["p_known"] for r in _bkt_rows(project_id, user_id)}
    prereqs = [
        e["source"] for e in get_edges(project_id)
        if e.get("target") == target_kc and e.get("edge_type") == "prerequisite"
    ]
    if not prereqs:
        return 1.0
    if any(p not in bkt for p in prereqs):
        return 0.0
    return min(1.0, min(bkt[p] for p in prereqs) / READINESS_THRESHOLD)


def queue_for_user(project_id: str, user_id: str, limit: int = 20) -> list[dict]:
    """Return an enriched SM-2 review queue."""
    rows = _sr_due_today(project_id, user_id)[:limit]
    metadata = _node_metadata(project_id)
    out: list[dict] = []
    for r in rows:
        meta = metadata.get(r["kc_id"], {})
        title = meta.get("title", r["kc_id"])
        out.append({
            **r,
            "title": title,
            "path": meta.get("path", ""),
            "prompt": f"复习：{title}",
            "expected": "先自我解释核心定义，再打开页面核对细节。",
        })
    return out


__all__ = [
    "record_attempt",
    "record_confidence",
    "learner_state_summary",
    "readiness_score",
    "queue_for_user",
]
