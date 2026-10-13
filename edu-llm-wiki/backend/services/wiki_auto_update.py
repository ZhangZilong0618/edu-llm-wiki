"""Privacy-safe, retryable projections from learning events into the Wiki.

The graph/BKT/SM-2 tables are authoritative. This module maintains a
human-readable projection only: aggregate activity, a pseudonymous learner
snapshot, and managed blocks on relevant class/knowledge pages. Raw questions,
answers, LLM responses, and user identifiers never enter shared Markdown.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import threading
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from services.graph_store import connect
from storage.wiki_store import (
    ensure_dirs,
    make_frontmatter,
    parse_frontmatter,
    read_wiki_page,
    validate_project_id,
    wiki_path,
)

try:  # pragma: no cover - deployment is currently POSIX.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


_LOCKS: defaultdict[str, threading.RLock] = defaultdict(threading.RLock)
_START_MARK = "<!-- wiki-auto:learning-summary:start -->"
_END_MARK = "<!-- wiki-auto:learning-summary:end -->"
_SEMANTIC_START = "<!-- wiki-auto:semantic-snapshot:start -->"
_SEMANTIC_END = "<!-- wiki-auto:semantic-snapshot:end -->"
_INSIGHT_START = "<!-- wiki-auto:learning-insight:start -->"
_INSIGHT_END = "<!-- wiki-auto:learning-insight:end -->"
_EVENT_MARK_PREFIX = "<!-- wiki-event:"
_MAX_RECENT = 12
_MAX_TOPIC_LENGTH = 180
_MAX_SNAPSHOT_EVENTS = 100
_CLAIM_LEASE = 60.0
_LOGGER = logging.getLogger(__name__)


def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _iso(ts: float | None = None) -> str:
    return datetime.fromtimestamp(_now() if ts is None else ts, timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


def _short(value: Any, limit: int = _MAX_TOPIC_LENGTH) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def _digest(value: Any, limit: int = 24) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:limit]


def _number(value: Any, default: float = 0.0) -> float:
    """Coerce event telemetry without letting one malformed field abort a projection."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _user_token(project_id: str, user_id: str) -> str:
    return "u_" + _digest(f"{project_id}\x00{user_id}")


def _safe_user(value: str, project_id: str = "default") -> str:
    """Compatibility helper; never returns the caller's identifier."""
    return _user_token(project_id, str(value or "default"))


def _event_id(event_type: str, project_id: str, user_id: str, payload: dict) -> str:
    """Type-namespace IDs so assessment and mastery deliveries cannot clash."""
    explicit = payload.get("event_id") or payload.get("attempt_id")
    if explicit:
        base = str(explicit)
    else:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        base = _digest(f"{event_type}|{project_id}|{user_id}|{canonical}", 32)
    # Hash even caller-provided IDs (they may contain conversation IDs or
    # other identifying material). The hash remains stable for retries.
    return f"{event_type}:{_digest(base, 32)}"


def _event_marker(event_id: str) -> str:
    return _EVENT_MARK_PREFIX + _digest(event_id, 20) + " -->"


def _valid_page_path(page_path: str) -> str | None:
    if not page_path:
        return None
    candidate = Path(str(page_path))
    if candidate.is_absolute() or candidate.suffix.lower() != ".md":
        return None
    if any(part in {"", ".", ".."} for part in candidate.parts):
        return None
    return candidate.as_posix()


def _ensure_ledger_schema(conn) -> None:
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(wiki_update_events)")}
    for name, definition in (
        ("projection_status", "TEXT NOT NULL DEFAULT 'complete'"),
        ("attempt_count", "INTEGER NOT NULL DEFAULT 0"),
        ("claimed_at", "REAL"),
        ("completed_at", "REAL"),
        ("last_error", "TEXT"),
    ):
        if name not in columns:
            conn.execute(f"ALTER TABLE wiki_update_events ADD COLUMN {name} {definition}")


def _redacted_payload(event_type: str, payload: dict) -> dict:
    """Return only fields required to render an aggregate projection."""
    if event_type == "dialogue_completed":
        cited = payload.get("cited_pages") or []
        if not isinstance(cited, (list, tuple)):
            cited = []
        return {
            "mode": str(payload.get("mode") or "ask")[:24],
            "conversation_token": _digest(payload.get("conversation_id")),
            "cited_paths": [
                p for item in cited[:8]
                if isinstance(item, dict)
                for p in [_valid_page_path(str(item.get("path") or ""))]
                if p
            ],
        }
    if event_type == "assessment_attempt":
        evaluation = payload.get("evaluation") or {}
        update = payload.get("learning_update") or {}
        bkt, sr = update.get("bkt") or {}, update.get("sr") or {}
        page = _valid_page_path(str(payload.get("related_page") or ""))
        return {
            "kc_id": str(payload.get("kc_id") or "")[:180],
            "related_page": page,
            "score": round(_number(evaluation.get("score", payload.get("score", 0)) or 0), 4),
            "p_known": round(_number(bkt.get("p_known", 0) or 0), 6),
            "due_at": sr.get("due_at"),
            "mode": str(payload.get("mode") or "practice")[:24],
        }
    if event_type == "learning_event":
        page = _valid_page_path(str(payload.get("related_page") or ""))
        return {
            "event_kind": str(payload.get("event_kind") or "read")[:32],
            "related_page": page,
            "kc_id": str(payload.get("kc_id") or "")[:180],
            "mode": str(payload.get("mode") or "")[:24],
        }
    if event_type in {"mastery_change", "review_completed", "question_issued"}:
        page = _valid_page_path(str(payload.get("related_page") or ""))
        result = {
            "kc_id": str(payload.get("kc_id") or "")[:180],
            "related_page": page,
            "p_known": round(_number(payload.get("p_known", 0) or 0), 6),
            "due_at": payload.get("due_at"),
            "mode": str(payload.get("mode") or "")[:24],
        }
        if event_type == "review_completed":
            evaluation = payload.get("evaluation") or {}
            update = payload.get("learning_update") or {}
            result["score"] = round(_number(evaluation.get("score", 0) or 0), 4)
            result["p_known"] = round(_number((update.get("bkt") or {}).get("p_known", result["p_known"]) or 0), 6)
            result["due_at"] = (update.get("sr") or {}).get("due_at", result["due_at"])
        return result
    return {"kind": str(payload.get("kind") or event_type)[:64]}


def _claim(project_id: str, user_id: str, event_id: str, event_type: str, payload: dict) -> tuple[bool, str]:
    now = _now()
    redacted = _redacted_payload(event_type, payload)
    with connect(project_id) as conn:
        # The in-process lock protects normal ASGI workers, while IMMEDIATE
        # makes the claim safe when several server processes share one SQLite
        # database. Without this transaction two workers could both observe an
        # absent row and append the same event to Markdown.
        conn.execute("BEGIN IMMEDIATE")
        try:
            _ensure_ledger_schema(conn)
            # Installations created by the previous projector used a bare
            # explicit id (for example ``a1``). Treat that row as a duplicate
            # only when its event type agrees; this preserves replay safety
            # without reviving old cross-event collisions.
            legacy_id = str(
                payload.get("event_id")
                or payload.get("attempt_id")
                or event_id
            )
            row = conn.execute(
                """SELECT event_id,projection_status,claimed_at FROM wiki_update_events
                   WHERE project_id=? AND user_id=?
                     AND ((event_id=? AND event_type=?)
                          OR (event_id=? AND event_type=?))
                   ORDER BY CASE WHEN event_id=? THEN 0 ELSE 1 END LIMIT 1""",
                (project_id, user_id, event_id, event_type, legacy_id, event_type, event_id),
            ).fetchone()
            if row:
                stored_id = str(row[0])
                status, claimed_at = str(row[1] or "complete"), float(row[2] or 0)
                if status == "complete":
                    conn.execute("COMMIT")
                    return False, "duplicate"
                if status == "pending" and now - claimed_at < _CLAIM_LEASE:
                    conn.execute("COMMIT")
                    return False, "in_progress"
                if stored_id != event_id:
                    conn.execute(
                        "UPDATE wiki_update_events SET event_id=? WHERE project_id=? AND user_id=? AND event_id=?",
                        (event_id, project_id, user_id, stored_id),
                    )
                conn.execute(
                    """UPDATE wiki_update_events SET projection_status='pending',
                       attempt_count=COALESCE(attempt_count,0)+1, claimed_at=?,
                       last_error=NULL, payload_json=?, event_type=?
                        WHERE project_id=? AND user_id=? AND event_id=?""",
                    (now, json.dumps(redacted, ensure_ascii=False), event_type, project_id, user_id, event_id),
                )
                conn.execute("COMMIT")
                return True, "retry"
            conn.execute(
                """INSERT INTO wiki_update_events(
                   project_id,user_id,event_id,event_type,payload_json,created_at,
                   projection_status,attempt_count,claimed_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (project_id, user_id, event_id, event_type,
                 json.dumps(redacted, ensure_ascii=False), now, "pending", 1, now),
            )
            conn.execute("COMMIT")
            return True, "claimed"
        except Exception:
            conn.execute("ROLLBACK")
            raise


def _finish(project_id: str, user_id: str, event_id: str) -> None:
    with connect(project_id) as conn:
        _ensure_ledger_schema(conn)
        conn.execute(
            "UPDATE wiki_update_events SET projection_status='complete',completed_at=?,last_error=NULL WHERE project_id=? AND user_id=? AND event_id=?",
            (_now(), project_id, user_id, event_id),
        )


def _fail(project_id: str, user_id: str, event_id: str, error: Exception) -> None:
    with connect(project_id) as conn:
        _ensure_ledger_schema(conn)
        conn.execute(
            "UPDATE wiki_update_events SET projection_status='failed',last_error=? WHERE project_id=? AND user_id=? AND event_id=?",
            (_short(type(error).__name__ + ": " + str(error), 240), project_id, user_id, event_id),
        )


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _page_activity_block(lines: list[str]) -> str:
    return f"{_START_MARK}\n## 自动学习摘要\n{'\n'.join(lines[:_MAX_RECENT])}\n{_END_MARK}"


def _semantic_snapshot_block(
    project_id: str,
    page_path: str,
    event_type: str,
    payload: dict,
    event_id: str,
    *,
    at: float | None = None,
) -> str:
    """Build a safe, human-readable semantic snapshot for a projected page.

    The event ledger remains authoritative.  This block is a disposable view
    that makes the learning meaning visible next to the audit line: which
    knowledge page was involved, what kind of learning signal arrived, and
    the latest BKT/SM-2 values when an answer was graded.  Raw answers,
    prompts, model output, and user identifiers are deliberately excluded.
    """
    event_names = {
        "dialogue_completed": "dialogue_completed（对话学习）",
        "learning_event": "learning_event（学习活动）",
        "question_issued": "question_issued（题目发放）",
        "assessment_attempt": "assessment_attempt（练习结果）",
        "review_completed": "review_completed（复习结果）",
        "mastery_change": "mastery_change（掌握状态）",
    }
    lines = [
        _SEMANTIC_START,
        "## 学习语义快照",
        f"- 投影页面: `{page_path}`",
        f"- 最近事件: {event_names.get(event_type, event_type)}",
        f"- 更新时间: {_iso(at)}",
    ]

    related = payload.get("related_page")
    cited = [str(path) for path in (payload.get("cited_paths") or []) if path]
    paths = list(dict.fromkeys(([str(related)] if related else []) + cited))
    if paths:
        lines.append("- 关联知识页: " + ", ".join(f"`{path}`" for path in paths[:8]))
    kc_id = str(payload.get("kc_id") or "").strip()
    if kc_id:
        lines.append(f"- 知识点标识: `{kc_id[:180]}`")
    event_kind = str(payload.get("event_kind") or "").strip()
    if event_kind:
        lines.append(f"- 活动类型: `{event_kind[:32]}`")
    mode = str(payload.get("mode") or "").strip()
    if mode:
        lines.append(f"- 交互模式: `{mode[:24]}`")
    if event_type in {"assessment_attempt", "review_completed"}:
        lines.append(f"- 最近得分: {_number(payload.get('score'), 0.0):.3f}")
    if event_type in {"assessment_attempt", "review_completed", "mastery_change"}:
        lines.append(f"- BKT 掌握度: {_number(payload.get('p_known'), 0.0):.3f}")
        due_at = payload.get("due_at")
        if due_at:
            try:
                lines.append(f"- SM-2 下次复习: {_iso(float(due_at))}")
            except (TypeError, ValueError):
                pass
    lines.append(f"- 事件标识: `{_digest(event_id, 16)}`")
    lines.append(_SEMANTIC_END)
    return "\n".join(lines)


def _teaching_event_types_for_page(page_path: str) -> set[str]:
    """Return event types routed to one TeachingObject page.

    TeachingObject pages are semantic class views rather than learner-owned
    pages.  Their insight block therefore aggregates only the event types
    that the routing table says can provide evidence for that class.  This
    keeps, for example, a LearningState page from counting ordinary dialogue
    events that never update mastery.
    """
    safe_path = _valid_page_path(page_path)
    if not safe_path or not safe_path.startswith("teaching/"):
        return set()
    try:
        from services.ontology_v2 import TEACHING_CLASS_GROUPS

        # Resolve the page to ontology class references.  The root index
        # aggregates every group, while a group index aggregates its own
        # classes; a class page maps to one exact reference.
        page_refs: set[str] = set()
        if safe_path == "teaching/index.md":
            page_refs = {
                f"{group_name}/{class_name}"
                for group_name, group in TEACHING_CLASS_GROUPS.items()
                for class_name in group.get("classes", ())
            }
        else:
            parts = safe_path.split("/")
            if len(parts) != 3:
                return set()
            folder, leaf = parts[1], parts[2]
            for group_name, group in TEACHING_CLASS_GROUPS.items():
                if str(group.get("folder")) != folder:
                    continue
                classes = set(str(item) for item in group.get("classes", ()))
                if leaf == "index.md":
                    page_refs.update(f"{group_name}/{name}" for name in classes)
                else:
                    class_name = Path(leaf).stem
                    if class_name in classes:
                        page_refs.add(f"{group_name}/{class_name}")
                break
        return {
            event_type
            for event_type, routes in _TEACHING_CLASSES.items()
            if any(route in page_refs for route in routes)
        }
    except (ImportError, AttributeError, TypeError):
        return set()


def _insight_event_payload(payload: dict) -> dict[str, Any]:
    """Extract only safe insight fields from a redacted event payload."""
    kc_id = str(payload.get("kc_id") or "").strip() or None
    related = _valid_page_path(str(payload.get("related_page") or ""))
    cited = [
        path for item in (payload.get("cited_paths") or [])
        for path in [_valid_page_path(str(item or ""))]
        if path
    ]
    score: float | None = None
    p_known: float | None = None
    due_at: float | None = None
    if payload.get("score") is not None:
        score = _number(payload.get("score"), 0.0)
    if payload.get("p_known") is not None:
        p_known = _number(payload.get("p_known"), 0.0)
    if payload.get("due_at") is not None:
        try:
            due_at = float(payload.get("due_at"))
            if not math.isfinite(due_at):
                due_at = None
        except (TypeError, ValueError):
            due_at = None
    # A legacy redacted row may retain the nested shape.  Read it for
    # backwards-compatible rebuilds without ever copying the nested feedback.
    update = payload.get("learning_update") or {}
    if p_known is None:
        p_known_value = (update.get("bkt") or {}).get("p_known")
        if p_known_value is not None:
            p_known = _number(p_known_value, 0.0)
    if due_at is None:
        due_value = (update.get("sr") or {}).get("due_at")
        if due_value is not None:
            try:
                due_at = float(due_value)
                if not math.isfinite(due_at):
                    due_at = None
            except (TypeError, ValueError):
                due_at = None
    return {
        "kc_id": kc_id,
        "related_page": related,
        "score": score,
        "p_known": p_known,
        "due_at": due_at,
        "paths": list(dict.fromkeys(([related] if related else []) + cited)),
    }


def _learning_insight_block(
    project_id: str,
    page_path: str,
    event_type: str,
    payload: dict,
    event_id: str,
    *,
    at: float | None = None,
) -> str:
    """Build an aggregate, privacy-safe view of learning evidence for a page."""
    rows: list[tuple[str, dict, float, str]] = []
    try:
        with connect(project_id) as conn:
            stored = conn.execute(
                "SELECT event_type,payload_json,created_at,event_id "
                "FROM wiki_update_events WHERE project_id=? "
                "ORDER BY created_at ASC,event_id ASC",
                (project_id,),
            ).fetchall()
        for row in stored:
            try:
                item = json.loads(row[1] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(item, dict):
                rows.append((str(row[0]), item, float(row[2] or 0), str(row[3])))
    except Exception:
        # The primary learning operation should still succeed when a
        # projection database is temporarily unavailable.
        rows = []

    safe_page = _valid_page_path(page_path) or page_path
    teaching_event_types = _teaching_event_types_for_page(safe_page)
    is_teaching = safe_page.startswith("teaching/")

    def relevant(kind: str, item: dict) -> bool:
        if is_teaching:
            return kind in teaching_event_types
        related = _valid_page_path(str(item.get("related_page") or ""))
        cited = {
            path for raw in (item.get("cited_paths") or [])
            for path in [_valid_page_path(str(raw or ""))]
            if path
        }
        return safe_page == related or safe_page in cited

    matching = [entry for entry in rows if relevant(entry[0], entry[1])]
    # During a newly claimed event the ledger row is already present, but a
    # caller may invoke this helper directly in a test or repair script.
    if not any(row[3] == event_id for row in matching):
        matching.append((event_type, payload, _now() if at is None else at, event_id))
    if not matching:
        return ""

    event_names = {
        "dialogue_completed": "对话",
        "learning_event": "学习活动",
        "question_issued": "题目发放",
        "assessment_attempt": "练习结果",
        "review_completed": "复习结果",
        "mastery_change": "掌握更新",
    }
    counts: dict[str, int] = {}
    latest_score: float | None = None
    latest_score_time = -1.0
    latest_p_known: float | None = None
    latest_p_known_time = -1.0
    latest_due_at: float | None = None
    latest_due_time = -1.0
    latest_kc: str | None = None
    latest_paths: list[str] = []
    latest_kc_time = -1.0
    latest_kind = event_type
    latest_time = _now() if at is None else at
    for kind, item, timestamp, _stored_id in matching:
        counts[kind] = counts.get(kind, 0) + 1
        if timestamp >= latest_time:
            latest_time = timestamp
            latest_kind = kind
        parsed = _insight_event_payload(item)
        kc = parsed["kc_id"]
        paths = parsed["paths"]
        if timestamp >= latest_kc_time and (kc or paths):
            latest_kc = kc or latest_kc
            latest_paths = paths or latest_paths
            latest_kc_time = timestamp
        # Metrics should use the latest event that actually carries each
        # field; dialogue/read events must not erase the previous mastery.
        score = parsed["score"]
        if score is not None and timestamp >= latest_score_time:
            latest_score = score
            latest_score_time = timestamp
        p_known = parsed["p_known"]
        if p_known is not None and timestamp >= latest_p_known_time:
            latest_p_known = p_known
            latest_p_known_time = timestamp
        candidate_due = parsed["due_at"]
        if candidate_due is not None and timestamp >= latest_due_time:
            latest_due_at = candidate_due
            latest_due_time = timestamp

    total = len(matching)
    summary = " · ".join(
        f"{event_names.get(kind, kind)} {count}"
        for kind, count in counts.items()
    )
    lines = [
        _INSIGHT_START,
        "## 学习洞察",
        f"- 关联事件: {total} 次（{summary}）",
        f"- 最近事件: {event_names.get(latest_kind, latest_kind)} · {_iso(latest_time)}",
    ]
    if latest_kc:
        lines.append(f"- 最近知识点: `{_short(latest_kc, 180)}`")
    if latest_paths:
        lines.append("- 关联知识页: " + ", ".join(f"`{path}`" for path in latest_paths[:8]))
    if latest_score is not None:
        lines.append(f"- 最近得分: {latest_score:.3f}")
    if latest_p_known is not None:
        lines.append(f"- BKT 掌握度: {latest_p_known:.3f}")
    if latest_due_at is not None:
        lines.append(f"- SM-2 下次复习: {_iso(latest_due_at)}")
    lines.extend([
        f"- 事件摘要由账本自动维护；事件标识: `{_digest(event_id, 16)}`",
        _INSIGHT_END,
    ])
    return "\n".join(lines)


def _update_learning_insight(
    project_id: str,
    page_path: str,
    event_type: str,
    payload: dict,
    event_id: str,
    *,
    at: float | None = None,
) -> None:
    """Replace the managed learning insight block and preserve authored text."""
    safe_path = _valid_page_path(page_path)
    if not safe_path:
        return
    root = wiki_path(project_id).resolve()
    full = (root / safe_path).resolve()
    if root not in full.parents or not full.exists() or not read_wiki_page(safe_path, project_id=project_id):
        return
    raw = full.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(raw)
    block = _learning_insight_block(
        project_id, safe_path, event_type, payload, event_id, at=at
    )
    if not block:
        return
    pattern = re.compile(
        rf"{re.escape(_INSIGHT_START)}.*?{re.escape(_INSIGHT_END)}",
        flags=re.DOTALL,
    )
    if pattern.search(body):
        body = pattern.sub(block, body, count=1)
    else:
        body = body.rstrip() + "\n\n" + block
    _atomic_write(full, make_frontmatter(fm) + "\n" + body.rstrip() + "\n")


def _update_semantic_snapshot(
    project_id: str,
    page_path: str,
    event_type: str,
    payload: dict,
    event_id: str,
    *,
    at: float | None = None,
) -> None:
    """Replace the managed semantic block while preserving authored Markdown."""
    safe_path = _valid_page_path(page_path)
    if not safe_path:
        return
    root = wiki_path(project_id).resolve()
    full = (root / safe_path).resolve()
    if root not in full.parents or not full.exists() or not read_wiki_page(safe_path, project_id=project_id):
        return
    raw = full.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(raw)
    block = _semantic_snapshot_block(
        project_id, safe_path, event_type, payload, event_id, at=at
    )
    pattern = re.compile(
        rf"{re.escape(_SEMANTIC_START)}.*?{re.escape(_SEMANTIC_END)}",
        flags=re.DOTALL,
    )
    if pattern.search(body):
        body = pattern.sub(block, body, count=1)
    else:
        body = body.rstrip() + "\n\n" + block
    _atomic_write(full, make_frontmatter(fm) + "\n" + body.rstrip() + "\n")


def _update_page_summary(project_id: str, page_path: str, line: str) -> None:
    safe_path = _valid_page_path(page_path)
    if not safe_path:
        return
    root = wiki_path(project_id).resolve()
    full = (root / safe_path).resolve()
    if root not in full.parents or not full.exists() or not read_wiki_page(safe_path, project_id=project_id):
        return
    raw = full.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(raw)
    old = re.search(rf"{re.escape(_START_MARK)}\n(.*?){re.escape(_END_MARK)}", body, flags=re.DOTALL)
    marker = next((part for part in line.split() if part.startswith(_EVENT_MARK_PREFIX)), "")
    if old and marker and marker in old.group(1):
        return
    prior = []
    if old:
        prior = [x for x in old.group(1).splitlines() if x.strip() and not x.startswith("## 自动学习摘要")]
        body = body[:old.start()].rstrip() + body[old.end():]
    lines = [line] + [x for x in prior if x != line]
    _atomic_write(full, make_frontmatter(fm) + "\n" + body.rstrip() + "\n\n" + _page_activity_block(lines) + "\n")


def _append_daily_activity(
    project_id: str,
    event_type: str,
    payload: dict,
    event_id: str,
    *,
    at: float | None = None,
) -> None:
    wp = wiki_path(project_id)
    event_time = _now() if at is None else at
    day = datetime.fromtimestamp(event_time, timezone.utc).strftime("%Y-%m-%d")
    path = wp / "learning" / "activity" / f"{day}.md"
    if path.exists():
        fm, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    else:
        fm, body = {"title": f"学习活动 · {day}", "type": "learning_event_log", "auto_managed": True, "created": _iso(event_time)}, f"# 学习活动 · {day}\n\n"
    marker = _event_marker(event_id)
    if marker in body:
        return
    names = {"dialogue_completed": "对话完成", "question_issued": "题目发放", "assessment_attempt": "练习完成", "review_completed": "复习完成", "mastery_change": "掌握状态更新", "learning_event": "学习事件"}
    count = len(payload.get("cited_paths") or []) + int(bool(payload.get("related_page")))
    suffix = f" · 关联知识页 {count} 个" if count else ""
    row = f"- {_iso(event_time)} · `{names.get(event_type, '学习活动')}`{suffix} {marker}"
    lines = body.rstrip().splitlines()
    header = lines[:2] if lines and lines[0].startswith("#") else []
    entries = [x for x in lines[len(header):] if x.startswith("-")]
    fm["updated"] = _iso(event_time)
    _atomic_write(path, make_frontmatter(fm) + "\n" + "\n".join(header + [""] + [row] + entries[:99]).rstrip() + "\n")


def _update_learner_snapshot(
    project_id: str,
    user_id: str,
    event_type: str,
    payload: dict,
    event_id: str,
    *,
    at: float | None = None,
) -> None:
    token = _user_token(project_id, user_id)
    path = wiki_path(project_id) / "learning" / "learners" / f"{token}.md"
    if path.exists():
        fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
    else:
        fm = {"title": "学习者活动摘要", "type": "learner_profile", "auto_managed": True,
              "privacy": "pseudonymous; enforce user-scoped ACL before serving", "user_token": token,
              "created": _iso(at), "interaction_count": 0, "attempt_count": 0, "recent_topics": [], "projection_event_ids": []}
    seen = list(fm.get("projection_event_ids") or [])
    if event_id in seen:
        return
    fm["projection_event_ids"] = (seen + [event_id])[-_MAX_SNAPSHOT_EVENTS:]
    fm["updated"] = _iso(at)
    fm["interaction_count"] = int(fm.get("interaction_count", 0) or 0) + (event_type == "dialogue_completed")
    fm["attempt_count"] = int(fm.get("attempt_count", 0) or 0) + (event_type in {"assessment_attempt", "review_completed"})
    topics = list(fm.get("recent_topics") or [])
    topic = _short(payload.get("related_page") or payload.get("kc_id"), 120)
    if topic:
        fm["recent_topics"] = [topic] + [x for x in topics if x != topic][:9]
    latest: dict[str, Any] = {"event": event_type, "time": _iso(at)}
    if event_type == "learning_event":
        latest.update({
            "event_kind": payload.get("event_kind"),
            "kc_id": payload.get("kc_id"),
            "related_page": payload.get("related_page"),
        })
    elif event_type in {"assessment_attempt", "review_completed"}:
        evaluation, update = payload.get("evaluation") or {}, payload.get("learning_update") or {}
        # Projected ledger payloads keep mastery values at the top level so
        # shared Wiki pages do not need the full private learning update.
        # Keep the nested fallback for events written before that redaction.
        bkt_p_known = (update.get("bkt") or {}).get("p_known")
        sr_due_at = (update.get("sr") or {}).get("due_at")
        flat_p_known = payload.get("p_known")
        flat_due_at = payload.get("due_at")
        latest.update({
            "score": evaluation.get("score", payload.get("score")),
            "kc_id": payload.get("kc_id"),
            "p_known": bkt_p_known if flat_p_known is None else flat_p_known,
            "due_at": sr_due_at if flat_due_at is None else flat_due_at,
        })
    elif event_type == "mastery_change":
        latest.update({"kc_id": payload.get("kc_id"), "p_known": payload.get("p_known"), "due_at": payload.get("due_at")})
    fm["last_event"] = latest
    body = ["# 学习者活动档案", "", "本页由学习事件自动维护。仅保存去标识化摘要；课程正文仍以知识页面为准。", "", "## 最近主题"]
    body.extend(f"- {x}" for x in fm.get("recent_topics") or [])
    body.extend(["", "## 最近一次事件", "", "```json", json.dumps(latest, ensure_ascii=False, indent=2), "```", ""])
    _atomic_write(path, make_frontmatter(fm) + "\n" + "\n".join(body))


# A projection event is deliberately attached to semantic objects instead of
# writing a private transcript into one page.  Keep this table as the single
# routing contract: the taxonomy validator below makes a newly added
# TeachingObject class fail loudly until an event can update it.  The routes
# describe *which* objects acquire evidence from an event; they do not imply
# that every class page is rewritten for every turn.
_TEACHING_CLASSES: dict[str, tuple[str, ...]] = {
    # Generic educational actions (read, exerciseStart, analysisView,
    # taskComplete) are recorded by clients that do not have a richer
    # assessment event. They still refresh the event/activity and coverage
    # projections without carrying transcript data.
    "learning_event": (
        "LearningEvents/LearningEvent", "LearningSupport/LearningResource",
        "LearningSupport/LearningActivity",
        "LearningPlanning/KnowledgeCoverageSnapshot",
        "LearningPlanning/KnowledgeCoverageRecord",
    ),
    # A dialogue can reveal a learner/profile assertion, a knowledge-coverage
    # signal and the resource/activity used to discuss the topic.
    "dialogue_completed": (
        "LearnerIdentity/Learner", "LearnerIdentity/LearnerProfile",
        "LearnerIdentity/ProfileAssertion",
        "LearningEvents/LearningEvent", "LearningEvents/DialogueRecord",
        "LearningPlanning/KnowledgeCoverageSnapshot",
        "LearningPlanning/KnowledgeCoverageRecord",
        "LearningPlanning/LearningObjective",
        "LearningSupport/LearningResource", "LearningSupport/LearningActivity",
    ),
    # Issuing a card creates the assessment artefact and marks question-bank
    # and path coverage, even before the learner submits an answer.
    "question_issued": (
        "LearnerIdentity/Learner", "LearnerIdentity/LearnerProfile",
        "LearningEvents/LearningEvent",
        "AssessmentObjects/Exercise", "AssessmentObjects/ExerciseOption",
        "AssessmentObjects/ExerciseTarget", "AssessmentObjects/ScoringRubric",
        "AssessmentObjects/MasteryUpdateRule",
        "LearningPlanning/KnowledgeCoverageSnapshot",
        "LearningPlanning/KnowledgeCoverageRecord",
        "LearningPlanning/LearningPath", "LearningPlanning/LearningPathStep",
        "LearningPlanning/LearningObjective",
        "LearningSupport/LearningResource", "LearningSupport/LearningActivity",
        "LearningSupport/CognitiveLevel",
    ),
    # A submission produces the event/attempt/result, updates mastery and
    # evidence, and may cause coverage/path adjustment.
    "assessment_attempt": (
        "LearnerIdentity/Learner", "LearnerIdentity/LearnerProfile",
        "LearnerIdentity/ProfileAssertion",
        "LearningEvents/LearningEvent", "LearningEvents/ExerciseAttempt",
        "AssessmentObjects/AssessmentResult", "AssessmentObjects/MasteryUpdateRule",
        "MasteryTracking/LearningState", "MasteryTracking/MasteryEvidence",
        "LearningPlanning/KnowledgeCoverageSnapshot",
        "LearningPlanning/KnowledgeCoverageRecord",
        "LearningPlanning/LearningPath", "LearningPlanning/LearningPathStep",
        "LearningPlanning/PathAdjustmentRecord",
        "LearningSupport/LearningActivity",
    ),
    # Reviews share the attempt/result semantics but remain a distinct event
    # for the daily log and SM-2 audit trail.
    "review_completed": (
        "LearnerIdentity/Learner", "LearnerIdentity/LearnerProfile",
        "LearningEvents/LearningEvent", "LearningEvents/ExerciseAttempt",
        "AssessmentObjects/AssessmentResult", "AssessmentObjects/MasteryUpdateRule",
        "MasteryTracking/LearningState", "MasteryTracking/MasteryEvidence",
        "LearningPlanning/KnowledgeCoverageSnapshot",
        "LearningPlanning/KnowledgeCoverageRecord",
        "LearningPlanning/LearningPath", "LearningPlanning/LearningPathStep",
        "LearningPlanning/PathAdjustmentRecord",
        "LearningSupport/LearningActivity",
    ),
    # This event is emitted by the observer layer (including legacy test
    # routes), so it updates the durable mastery and planning views even when
    # no chat card was involved.
    "mastery_change": (
        "LearnerIdentity/Learner", "LearnerIdentity/LearnerProfile",
        "LearnerIdentity/ProfileAssertion",
        "LearningEvents/LearningEvent",
        "MasteryTracking/LearningState", "MasteryTracking/MasteryEvidence",
        "LearningPlanning/KnowledgeCoverageSnapshot",
        "LearningPlanning/KnowledgeCoverageRecord",
        "LearningPlanning/LearningPath", "LearningPlanning/LearningPathStep",
        "LearningPlanning/PathAdjustmentRecord",
        "LearningSupport/LearningActivity",
    ),
}


def _validate_teaching_event_routes() -> None:
    """Validate routing against the ontology taxonomy at import time.

    A taxonomy edit must not silently create an orphan Wiki page that never
    receives an automatic update.  Import-time validation also catches a
    misspelled group/class before the first learner event reaches disk.
    """
    from services.ontology_v2 import TEACHING_CLASS_GROUPS

    known = {
        f"{group_name}/{class_name}"
        for group_name, group in TEACHING_CLASS_GROUPS.items()
        for class_name in group.get("classes", ())
    }
    routed = {ref for refs in _TEACHING_CLASSES.values() for ref in refs}
    unknown = sorted(routed - known)
    missing = sorted(known - routed)
    if unknown or missing:
        raise ValueError(
            "Invalid TeachingObject event routes: "
            f"unknown={unknown}, missing={missing}"
        )


_validate_teaching_event_routes()


def _teaching_page_paths(class_refs: tuple[str, ...]) -> list[str]:
    # The event projector and Wiki directory must use the same taxonomy.  A
    # failed ontology import is a configuration/deployment error; silently
    # dropping these pages would make event projections appear successful
    # while leaving the TeachingObject Wiki stale.
    from services.ontology_v2 import TEACHING_CLASS_GROUPS

    folders = {name: str(group.get("folder")) for name, group in TEACHING_CLASS_GROUPS.items()}
    out = ["teaching/index.md"]
    seen_groups: set[str] = set()
    for ref in class_refs:
        group, _, cls = ref.partition("/")
        if folders.get(group) and cls:
            if group not in seen_groups:
                out.append(f"teaching/{folders[group]}/index.md")
                seen_groups.add(group)
            out.append(f"teaching/{folders[group]}/{cls}.md")
    return list(dict.fromkeys(out))


def _project(event_type: str, project_id: str, user_id: str, payload: dict) -> dict:
    validate_project_id(project_id)
    user_id = str(user_id or "default")
    ensure_dirs(project_id=project_id)
    event_id = _event_id(event_type, project_id, user_id, payload)
    with _LOCKS[f"{project_id}:{user_id}"]:
        try:
            claimed, status = _claim(project_id, user_id, event_id, event_type, payload)
        except Exception as error:
            # Caller routes may elect to keep the primary learning action
            # successful when Markdown is unavailable. Leave a clear,
            # privacy-safe operational signal rather than silently losing it.
            _LOGGER.exception(
                "Wiki projection event claim failed project=%s type=%s id=%s error=%s",
                project_id, event_type, event_id, type(error).__name__,
            )
            return {"status": "failed", "event_id": event_id, "error": type(error).__name__}
        if not claimed:
            return {"status": status, "event_id": event_id}
        try:
            wp = wiki_path(project_id)
            with _file_lock(wp / ".wiki-auto-update.lock"):
                redacted = _redacted_payload(event_type, payload)
                _render_event(
                    project_id,
                    user_id,
                    event_type,
                    redacted,
                    event_id,
                    at=_now(),
                )
            _finish(project_id, user_id, event_id)
        except Exception as error:
            _fail(project_id, user_id, event_id, error)
            _LOGGER.warning(
                "Wiki projection failed project=%s type=%s id=%s error=%s",
                project_id, event_type, event_id, type(error).__name__,
            )
            return {"status": "failed", "event_id": event_id, "error": type(error).__name__}
        return {"status": "updated", "event_id": event_id}


def _render_event(
    project_id: str,
    user_id: str,
    event_type: str,
    payload: dict,
    event_id: str,
    *,
    at: float | None = None,
) -> None:
    """Render one already-redacted event without touching its ledger row.

    The normal path calls this after claiming an event.  Rebuild/replay paths
    also call it with the ledger's original timestamp and stable event id, so
    the Markdown projection can be recreated after a deleted or corrupted
    generated file without creating a second ledger row.
    """
    event_at = _now() if at is None else at
    _append_daily_activity(project_id, event_type, payload, event_id, at=event_at)
    _update_learner_snapshot(
        project_id, user_id, event_type, payload, event_id, at=event_at
    )
    marker = _event_marker(event_id)
    labels = {
        "dialogue_completed": "对话涉及",
        "question_issued": "题目发放",
        "assessment_attempt": "练习反馈",
        "review_completed": "复习完成",
        "mastery_change": "掌握状态更新",
    }
    line = f"- {_iso(event_at)} · {labels.get(event_type, '学习活动')}（自动汇总） {marker}"
    pages = list(payload.get("cited_paths") or [])
    if payload.get("related_page"):
        pages.append(str(payload["related_page"]))
    pages.extend(_teaching_page_paths(_TEACHING_CLASSES.get(event_type, ())))
    for page in dict.fromkeys(pages):
        _update_page_summary(project_id, page, line)
        _update_semantic_snapshot(
            project_id,
            page,
            event_type,
            payload,
            event_id,
            at=event_at,
        )
        _update_learning_insight(
            project_id,
            page,
            event_type,
            payload,
            event_id,
            at=event_at,
        )


def _clear_generated_projection(project_id: str) -> None:
    """Remove only generated projection blocks/files before a full rebuild."""
    root = wiki_path(project_id).resolve()
    for path in root.rglob("*.md"):
        if path.parts[-3:-1] == ("learning", "activity"):
            continue
        try:
            raw = path.read_text(encoding="utf-8")
            fm, body = parse_frontmatter(raw)
        except (OSError, UnicodeError):
            continue
        if not any(marker in body for marker in (_START_MARK, _SEMANTIC_START, _INSIGHT_START)):
            continue
        body = re.sub(
            rf"\n?{re.escape(_START_MARK)}.*?{re.escape(_END_MARK)}\n?",
            "\n",
            body,
            flags=re.DOTALL,
        )
        body = re.sub(
            rf"\n?{re.escape(_SEMANTIC_START)}.*?{re.escape(_SEMANTIC_END)}\n?",
            "\n",
            body,
            flags=re.DOTALL,
        )
        body = re.sub(
            rf"\n?{re.escape(_INSIGHT_START)}.*?{re.escape(_INSIGHT_END)}\n?",
            "\n",
            body,
            flags=re.DOTALL,
        )
        _atomic_write(path, make_frontmatter(fm) + "\n" + body.strip() + "\n")

    activity_root = root / "learning" / "activity"
    if activity_root.exists():
        for path in activity_root.glob("*.md"):
            try:
                fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                continue
            if fm.get("auto_managed"):
                path.unlink(missing_ok=True)

    learner_root = root / "learning" / "learners"
    if learner_root.exists():
        for path in learner_root.glob("*.md"):
            try:
                fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                continue
            if fm.get("auto_managed"):
                path.unlink(missing_ok=True)


def rebuild_projection(
    project_id: str = "default",
    *,
    include_failed: bool = True,
) -> dict:
    """Rebuild all generated Wiki learning projections from the SQLite ledger.

    SQLite is the event ledger and learning-state authority.  This operation
    clears only marked/auto-managed output, replays redacted event payloads in
    their original order, and leaves authored Markdown untouched.  It is safe
    to run repeatedly and is useful after restoring a Wiki checkout or fixing
    a projector bug.
    """
    validate_project_id(project_id)
    ensure_dirs(project_id=project_id)
    statuses = ("complete", "failed", "pending") if include_failed else ("complete",)
    placeholders = ",".join("?" for _ in statuses)
    with _LOCKS[f"{project_id}:__rebuild__"]:
        with _file_lock(wiki_path(project_id) / ".wiki-auto-update.lock"):
            with connect(project_id) as conn:
                # Older projects predate the retry ledger columns.  Apply the
                # additive migration before filtering by projection status so
                # a rebuild remains safe when the user switches projects.
                _ensure_ledger_schema(conn)
                rows = conn.execute(
                    f"""SELECT user_id,event_id,event_type,payload_json,created_at
                        FROM wiki_update_events
                        WHERE project_id=? AND projection_status IN ({placeholders})
                        ORDER BY created_at ASC,event_id ASC""",
                    (project_id, *statuses),
                ).fetchall()
            _clear_generated_projection(project_id)
            rendered = 0
            skipped = 0
            for row in rows:
                try:
                    payload = json.loads(row[3] or "{}")
                    if not isinstance(payload, dict):
                        raise ValueError("payload is not an object")
                    _render_event(
                        project_id,
                        str(row[0] or "default"),
                        str(row[2]),
                        payload,
                        str(row[1]),
                        at=float(row[4]),
                    )
                    rendered += 1
                except (ValueError, TypeError, OSError, UnicodeError, KeyError):
                    # One malformed historical row must not prevent the rest
                    # of the project from being reconstructed.
                    skipped += 1
    return {"status": "rebuilt", "events": rendered, "skipped": skipped}


def replay_failed_events(
    project_id: str = "default",
    *,
    user_id: str | None = None,
    limit: int = 100,
) -> dict:
    """Retry failed/stale pending rows using their redacted ledger payload."""
    validate_project_id(project_id)
    ensure_dirs(project_id=project_id)
    limit = max(1, min(int(limit), 1000))
    params: list[Any] = [project_id]
    user_clause = ""
    if user_id is not None:
        user_clause = " AND user_id=?"
        params.append(str(user_id))
    params.append(limit)
    with _LOCKS[f"{project_id}:__replay__"]:
        with _file_lock(wiki_path(project_id) / ".wiki-auto-update.lock"):
            with connect(project_id) as conn:
                # The replay endpoint is also used for projects created by an
                # earlier release, where the status/lease columns do not yet
                # exist.  The migration is additive and idempotent.
                _ensure_ledger_schema(conn)
                rows = conn.execute(
                    """SELECT user_id,event_id,event_type,payload_json,created_at
                       FROM wiki_update_events
                       WHERE project_id=?"""
                    + user_clause
                    + " AND (projection_status='failed' OR "
                    + "(projection_status='pending' AND "
                    + "(claimed_at IS NULL OR claimed_at < ?)))"
                    + " ORDER BY created_at ASC LIMIT ?",
                    tuple(params[:-1] + [_now() - _CLAIM_LEASE, params[-1]]),
                ).fetchall()
            replayed = 0
            skipped = 0
            for row in rows:
                try:
                    payload = json.loads(row[3] or "{}")
                except (TypeError, ValueError, json.JSONDecodeError):
                    skipped += 1
                    continue
                if not isinstance(payload, dict):
                    skipped += 1
                    continue
                try:
                    with connect(project_id) as conn:
                        conn.execute(
                            """UPDATE wiki_update_events
                               SET projection_status='pending',
                                   attempt_count=COALESCE(attempt_count,0)+1,
                                   claimed_at=?, last_error=NULL
                               WHERE project_id=? AND user_id=? AND event_id=?""",
                            (_now(), project_id, str(row[0] or "default"), str(row[1])),
                        )
                    _render_event(
                        project_id,
                        str(row[0] or "default"),
                        str(row[2]),
                        payload,
                        str(row[1]),
                        at=float(row[4]),
                    )
                    _finish(project_id, str(row[0] or "default"), str(row[1]))
                    replayed += 1
                except Exception as error:
                    _fail(project_id, str(row[0] or "default"), str(row[1]), error)
    return {"status": "replayed", "events": replayed, "skipped": skipped}


def record_learning_event(
    project_id: str,
    user_id: str,
    *,
    event_kind: str,
    related_page: str | None = None,
    kc_id: str | None = None,
    mode: str = "",
    event_id: str | None = None,
) -> dict:
    """Project a redacted educational action (read/start/view/complete)."""
    event_id = event_id or f"{event_kind}:{related_page or kc_id or 'unknown'}:{_digest(str(user_id), 12)}"
    return _project(
        "learning_event",
        project_id,
        user_id,
        {
            "event_id": event_id,
            "event_kind": event_kind,
            "related_page": related_page,
            "kc_id": kc_id,
            "mode": mode,
        },
    )


def record_dialogue(project_id: str, user_id: str, *, query: str, response: str, conversation_id: str | None = None, cited_pages: list[dict] | None = None, mode: str = "ask", event_id: str | None = None) -> dict:
    if not event_id:
        event_id = f"{conversation_id or 'turn'}:{_digest(query + '\n' + response, 16)}"
    return _project("dialogue_completed", project_id, user_id, {"event_id": event_id, "conversation_id": conversation_id, "query": query, "response": response, "cited_pages": cited_pages or [], "mode": mode})


def record_question(project_id: str, user_id: str, *, question_id: str, kc_id: str | None = None, related_page: str | None = None, mode: str = "practice", event_id: str | None = None) -> dict:
    return _project("question_issued", project_id, user_id, {"event_id": event_id or question_id, "question_id": question_id, "kc_id": kc_id, "related_page": related_page, "mode": mode})


def record_attempt(project_id: str, user_id: str, *, attempt_id: str, question_id: str, kc_id: str | None = None, related_page: str | None = None, evaluation: dict | None = None, learning_update: dict | None = None, mode: str = "practice") -> dict:
    return _project("assessment_attempt", project_id, user_id, {"event_id": attempt_id, "attempt_id": attempt_id, "question_id": question_id, "kc_id": kc_id, "related_page": related_page, "evaluation": evaluation or {}, "learning_update": learning_update or {}, "mode": mode})


def record_review(
    project_id: str,
    user_id: str,
    *,
    review_id: str,
    kc_id: str | None = None,
    related_page: str | None = None,
    evaluation: dict | None = None,
    learning_update: dict | None = None,
) -> dict:
    """Project one completed due-card review without storing its transcript."""
    return _project(
        "review_completed",
        project_id,
        user_id,
        {
            "event_id": review_id,
            "kc_id": kc_id,
            "related_page": related_page,
            "evaluation": evaluation or {},
            "learning_update": learning_update or {},
            "mode": "review",
        },
    )


def handle_event(event: dict) -> dict | None:
    event_type = str(event.get("event_type") or "")
    project_id = event.get("project_id", "default")
    payload = dict(event.get("payload") or {})
    user_id = payload.pop("user_id", "default")
    if event_type == "dialogue_completed":
        return record_dialogue(project_id, user_id, **payload)
    if event_type == "learning_event":
        return record_learning_event(project_id, user_id, **payload)
    if event_type == "question_issued":
        return record_question(project_id, user_id, **payload)
    if event_type == "assessment_attempt":
        payload.pop("event_id", None)
        return record_attempt(project_id, user_id, **payload)
    if event_type == "review_completed":
        return record_review(project_id, user_id, **payload)
    if event_type == "mastery_change":
        return _project("mastery_change", project_id, user_id, payload)
    return None


__all__ = [
    "record_learning_event",
    "record_dialogue",
    "record_question",
    "record_attempt",
    "record_review",
    "handle_event",
    "rebuild_projection",
    "replay_failed_events",
]
