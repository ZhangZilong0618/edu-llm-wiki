"""Learning-plan persistence: snapshot, deterministic diff, user adjustments.

``build_learning_path`` (services/learning/path.py) is a pure derived view —
recomputed on every call, never stored. This module adds the persistence layer
the conversational planning skill needs:

- plan file ``learning/plan/<user_token>.md``: frontmatter snapshot
  (graph + mastery fingerprints, overlay operations) plus a human-readable
  layered markdown body;
- ``plan_diff``: deterministic "stored snapshot vs current state" comparison
  (new pages, new prerequisite edges, mastery flips). The agent reads this and
  decides whether a rebuild is warranted before touching the file;
- ``apply_adjustments``: user edits are an append-only overlay of operations
  (move_before / move_to_front / remove / annotate). The plan is always
  re-derived from the current graph and then replayed through the overlay, so
  adjustments survive graph growth without drifting from the topology, and
  every adjustment stays auditable in the file.

The overlay model also defines rebuild semantics: ``rebuild_learning_plan``
regenerates from scratch and clears the overlay (the conversation keeps the
history), while plain adjustments keep replaying it.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from services.graph_store import get_edges, get_nodes
from services.learning.path import MASTERY_THRESHOLD, PREREQ_EDGE_TYPES, build_learning_path
from storage.wiki_store import make_frontmatter, parse_frontmatter, wiki_path

if TYPE_CHECKING:
    from pathlib import Path

_ADJUST_OPS = {"move_before", "move_to_front", "remove", "annotate"}
_STATUS_MARK = {
    "mastered": "✅",
    "ready": "🟢",
    "upcoming": "⏳",
    "unresolved": "⚠️",
}


def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _iso(ts: float | None = None) -> str:
    return datetime.fromtimestamp(_now() if ts is None else ts, timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


def _digest(value: str, limit: int = 24) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:limit]


def _user_token(project_id: str, user_id: str) -> str:
    # Mirrors wiki_auto_update._user_token so the plan file name matches the
    # learner-file naming convention without importing its privates.
    return "u_" + _digest(f"{project_id}\x00{user_id}")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def plan_file_path(project_id: str, user_id: str) -> Path:
    return wiki_path(project_id) / "learning" / "plan" / f"{_user_token(project_id, user_id)}.md"


# ---------------------------------------------------------------------------
# Fingerprints and diff
# ---------------------------------------------------------------------------

def _prereq_pairs(project_id: str) -> list[tuple[str, str]]:
    node_ids = {n["id"] for n in get_nodes(project_id)}
    pairs = []
    for edge in get_edges(project_id):
        if edge.get("edge_type") not in PREREQ_EDGE_TYPES:
            continue
        source, target = edge.get("source", ""), edge.get("target", "")
        if source in node_ids and target in node_ids and source != target:
            pairs.append((source, target))
    return sorted(set(pairs))


def _bkt_states(project_id: str, user_id: str) -> dict[str, float]:
    from services.graph_store import connect

    with connect(project_id) as conn:
        rows = conn.execute(
            "SELECT kc_id, p_known FROM bkt_params WHERE project_id=? AND user_id=?",
            (project_id, user_id),
        ).fetchall()
    return {str(r["kc_id"]): round(float(r["p_known"]), 4) for r in rows}


def _fingerprints(project_id: str, user_id: str) -> dict:
    nodes = sorted(n["id"] for n in get_nodes(project_id))
    pairs = _prereq_pairs(project_id)
    bkt = _bkt_states(project_id, user_id)
    return {
        "graph": {
            "node_count": len(nodes),
            "prereq_edge_count": len(pairs),
            "nodes_digest": _digest("\n".join(nodes)),
            "prereq_edges_digest": _digest("\n".join(f"{s} -> {t}" for s, t in pairs)),
        },
        "mastery": {
            "n_kcs": len(bkt),
            "mastered_count": sum(1 for p in bkt.values() if p >= MASTERY_THRESHOLD),
            "p_known_digest": _digest(json.dumps(bkt, sort_keys=True)),
            "mastered_ids": sorted(k for k, p in bkt.items() if p >= MASTERY_THRESHOLD),
        },
    }


def plan_diff(project_id: str, user_id: str) -> dict:
    """Deterministic comparison between the stored plan snapshot and now.

    The agent uses this to decide between ``rebuild_learning_plan`` and just
    summarising the stored plan; nothing here decides on its own.
    """
    path = plan_file_path(project_id, user_id)
    if not path.exists():
        return {"exists": False}
    fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
    stored_graph = fm.get("graph_fingerprint") or {}
    stored_mastery = fm.get("mastery_fingerprint") or {}

    current = _fingerprints(project_id, user_id)
    nodes = {n["id"]: n for n in get_nodes(project_id)}

    def labels(ids: list[str]) -> list[str]:
        return [nodes.get(n, {}).get("label", n) for n in ids]

    stored_ids = set(fm.get("node_ids") or []) or set()
    current_ids = set(nodes)
    if not stored_ids:
        # Older snapshot without the node id list: fall back to the digest.
        stored_ids = None

    new_nodes = labels(sorted(current_ids - stored_ids)) if stored_ids is not None else []
    removed_nodes = labels(sorted(stored_ids - current_ids)) if stored_ids is not None else []

    stored_mastered = set(stored_mastery.get("mastered_ids") or [])
    current_mastered = set(current["mastery"]["mastered_ids"])
    newly_mastered = labels(sorted(current_mastered - stored_mastered))
    no_longer_mastered = labels(sorted(stored_mastered - current_mastered))

    graph_changed = (
        stored_graph.get("nodes_digest") != current["graph"]["nodes_digest"]
        or stored_graph.get("prereq_edges_digest") != current["graph"]["prereq_edges_digest"]
    )
    mastery_changed = (
        stored_mastery.get("p_known_digest") != current["mastery"]["p_known_digest"]
        or stored_mastery.get("mastered_count") != current["mastery"]["mastered_count"]
    )

    parts = []
    if new_nodes:
        parts.append(f"新增 {len(new_nodes)} 个知识页({', '.join(new_nodes[:6])}{'…' if len(new_nodes) > 6 else ''})")
    if removed_nodes:
        parts.append(f"移除 {len(removed_nodes)} 个知识页")
    if graph_changed and not (new_nodes or removed_nodes):
        parts.append("先修关系有变化")
    if newly_mastered:
        parts.append(f"新掌握 {len(newly_mastered)} 项({', '.join(newly_mastered[:6])}{'…' if len(newly_mastered) > 6 else ''})")
    if no_longer_mastered:
        parts.append(f"{len(no_longer_mastered)} 项跌出掌握线")
    if mastery_changed and not (newly_mastered or no_longer_mastered):
        parts.append("掌握度数值有变化")

    return {
        "exists": True,
        "planned_at": fm.get("updated") or fm.get("created") or "unknown",
        "adjustment_count": int(fm.get("adjustment_count") or 0),
        "graph_changed": graph_changed,
        "mastery_changed": mastery_changed,
        "new_nodes": new_nodes,
        "removed_nodes": removed_nodes,
        "newly_mastered": newly_mastered,
        "no_longer_mastered": no_longer_mastered,
        "summary": ";".join(parts) if parts else "图谱与掌握状态与规划时一致,无实质变化",
    }


# ---------------------------------------------------------------------------
# Overlay application
# ---------------------------------------------------------------------------

def _prereq_closure(project_id: str) -> dict[str, set[str]]:
    """Transitive prerequisite set per node: {node_id: {all prereq ids}}.

    Prereq edges run prerequisite → dependent, so the closure walks backwards
    from each node to everything it (transitively) depends on.
    """
    backward: dict[str, list[str]] = {}
    for source, target in _prereq_pairs(project_id):
        backward.setdefault(target, []).append(source)
    closure: dict[str, set[str]] = {}

    def prereqs_of(node: str) -> set[str]:
        if node in closure:
            return closure[node]
        closure[node] = set()  # cycle guard
        result: set[str] = set()
        for prereq in backward.get(node, []):
            result.add(prereq)
            result |= prereqs_of(prereq)
        closure[node] = result
        return result

    return {node: prereqs_of(node) for node in {n["id"] for n in get_nodes(project_id)}}


def _resolve_ids(project_id: str, label: str, *, cluster: bool = False) -> list[str]:
    """Resolve a spoken label to node ids: exact match first, else the cluster.

    An exact label match returns only that node. A label that matches nothing
    exactly but is a substring of other labels (``液晶`` matching ``液晶发现``
    /``溶致型液晶``) resolves to the whole topic cluster, because “液晶的内容
    先不学” means the family, not one exact page. When a label does have an
    exact node but the request says the topic's content (“XX 的内容先不学”),
    pass ``cluster=True`` to take the whole substring family instead of the
    single page. Callers decide how to consume multi-matches: remove/annotate
    apply to every match, moves require a unique one.
    """
    label = (label or "").strip()
    if not label:
        return []
    nodes = get_nodes(project_id)
    if not cluster:
        exact = [
            node["id"]
            for node in nodes
            if label in (str(node.get("label") or ""), str(node.get("title") or ""))
        ]
        if exact:
            return list(dict.fromkeys(exact))
    members = [
        node["id"]
        for node in nodes
        if label in (str(node.get("label") or "") + str(node.get("title") or ""))
    ]
    return list(dict.fromkeys(members))


def _label_of_plan(plan: dict, node_id: str) -> str:
    for level in plan.get("levels", []):
        for node in level["nodes"]:
            if node["id"] == node_id:
                return node.get("label", node_id)
    return node_id


def apply_overlay(plan: dict, overlay: list[dict], *, closure: dict[str, set[str]]) -> dict:
    """Replay adjustment operations on a derived plan, in place.

    Returns an execution report for the caller (applied/skipped/rejected per
    operation) while the plan itself carries the visible effects: removed
    nodes filtered out, notes attached, and moved nodes lifted into the
    target's level.
    """
    report = {"applied": [], "skipped": [], "rejected": []}
    removed: dict[str, str] = {}
    notes: dict[str, list[str]] = {}

    for index, operation in enumerate(overlay):
        kind = operation.get("op")
        label = str(operation.get("node") or "").strip()
        if kind not in _ADJUST_OPS or not label:
            report["rejected"].append({"index": index, "reason": "未知操作或缺少 node 字段"})
            continue
        node_ids = operation.get("_node_ids") or []
        if not node_ids:
            report["skipped"].append({"index": index, "reason": f"找不到节点「{label}」"})
            continue
        if kind == "remove":
            note = str(operation.get("note") or "用户要求移除")
            removed_names = []
            for node_id in node_ids:
                removed[node_id] = note
                removed_names.append(_label_of_plan(plan, node_id))
            names = ", ".join(removed_names)
            report["applied"].append({
                "index": index,
                "detail": f"移除 {label}({names})" if names != label else f"移除 {label}",
            })
        elif kind == "annotate":
            note = str(operation.get("note") or "").strip()
            for node_id in node_ids:
                notes.setdefault(node_id, []).append(note)
            report["applied"].append({"index": index, "detail": f"备注 {label}"})
        elif kind == "move_before":
            if len(node_ids) > 1:
                report["rejected"].append({
                    "index": index,
                    "reason": f"「{label}」匹配多个节点,请用完整标题",
                })
                continue
            node_id = node_ids[0]
            before_id = operation.get("_before_id") or ""
            if not before_id:
                report["rejected"].append({
                    "index": index,
                    "reason": f"move_before 的目标「{operation.get('before')}」缺失或匹配多个节点",
                })
                continue
            if before_id in removed:
                report["skipped"].append({"index": index, "reason": "目标节点已被移除"})
                continue
            if before_id in closure.get(node_id, set()):
                report["rejected"].append({
                    "index": index,
                    "reason": f"「{operation.get('before')}」是「{label}」的先修,不能移到它前面",
                })
                continue
            _move_node_before(plan, node_id, before_id)
            report["applied"].append({"index": index, "detail": f"将 {label} 移到 {operation.get('before')} 所在层"})
        elif kind == "move_to_front":
            if len(node_ids) > 1:
                report["rejected"].append({
                    "index": index,
                    "reason": f"「{label}」匹配多个节点,请用完整标题",
                })
                continue
            _move_node_to_level(plan, node_ids[0], 0)
            report["applied"].append({"index": index, "detail": f"将 {label} 移到第 1 层"})

    # Collect labels before filtering: removed nodes must keep their display
    # names in the removal list.
    label_by_id = {
        node["id"]: node.get("label", node["id"])
        for level in plan.get("levels", [])
        for node in level["nodes"]
    }
    for level in plan.get("levels", []):
        level["nodes"] = [n for n in level["nodes"] if n["id"] not in removed]
    for node_id, node_notes in notes.items():
        for level in plan.get("levels", []):
            for node in level["nodes"]:
                if node["id"] == node_id:
                    node["user_notes"] = (node.get("user_notes") or []) + node_notes

    plan["removed_by_user"] = [
        {"label": label_by_id.get(node_id, node_id), "note": note}
        for node_id, note in removed.items()
    ]

    # A removal or a move can empty a level; drop empty levels and renumber
    # so "第 N 层" and the current-level progress stay truthful.
    plan["levels"] = [lv for lv in plan.get("levels", []) if lv["nodes"]]
    for index, level in enumerate(plan["levels"]):
        level["level"] = index + 1
    progress = plan.get("progress") or {}
    current = 0
    for level in plan["levels"]:
        if any(node["status"] != "mastered" for node in level["nodes"]):
            current = level["level"]
            break
    else:
        current = plan["levels"][-1]["level"] if plan["levels"] else 0
    progress["current_level"] = current
    if progress.get("total"):
        progress["mastered"] = sum(
            1
            for level in plan["levels"]
            for node in level["nodes"]
            if node["status"] == "mastered"
        )
    return report


def _find_level(plan: dict, node_id: str) -> int | None:
    for index, level in enumerate(plan.get("levels", [])):
        if any(node["id"] == node_id for node in level["nodes"]):
            return index
    return None


def _move_node_to_level(plan: dict, node_id: str, level_index: int) -> None:
    source = _find_level(plan, node_id)
    if source is None or source == level_index:
        return
    level = plan["levels"][source]
    node = next((n for n in level["nodes"] if n["id"] == node_id), None)
    if node is None:
        return
    level["nodes"] = [n for n in level["nodes"] if n["id"] != node_id]
    if not level["nodes"] and source != len(plan["levels"]) - 1:
        plan["levels"].pop(source)
    target = plan["levels"][min(level_index, len(plan["levels"]) - 1)]
    target["nodes"].insert(0, node)


def _move_node_before(plan: dict, node_id: str, before_id: str) -> None:
    before_level = _find_level(plan, before_id)
    if before_level is None:
        return
    _move_node_to_level(plan, node_id, before_level)


# ---------------------------------------------------------------------------
# Render, write, read, adjust
# ---------------------------------------------------------------------------

def _render_plan_markdown(plan: dict, *, reason: str, generated_at: str) -> str:
    progress = plan.get("progress") or {}
    lines = [
        f"# 学习规划 · {plan.get('project_id', '')}",
        "",
        f"> {generated_at} 生成 · 基于 {progress.get('total', 0)} 个知识节点"
        f" · {reason}",
        "",
        "## 进度",
        "",
        f"已掌握 {progress.get('mastered', 0)}/{progress.get('total', 0)}"
        f" · 当前推进到第 {progress.get('current_level', 0)} 层",
        "",
        "## 分层学习路径",
        "",
        "同一层 = 并列可学、顺序自由;层间 = 前层是后层的先修基础。",
        "",
    ]
    for level in plan.get("levels", []):
        lines.append(f"### 第 {level['level']} 层(可并行)")
        lines.append("")
        for node in level["nodes"]:
            mark = _STATUS_MARK.get(node.get("status", "upcoming"), "⏳")
            # Wikilinks make every topic clickable in the chat/preview
            # renderers; the path disambiguates non-unique page titles.
            page_path = str(node.get("page_path") or "").strip()
            label = node.get("label", node["id"])
            title_part = f"[[{page_path}|{label}]]" if page_path else f"**{label}**"
            line = f"- {mark} {title_part}"
            p_known = node.get("p_known")
            if p_known is not None:
                line += f" · 掌握 {p_known * 100:.0f}%"
            prereqs = node.get("prereq_labels") or []
            if prereqs:
                line += f" · 先修: {', '.join(prereqs[:4])}"
            lines.append(line)
            for note in node.get("user_notes") or []:
                lines.append(f"  - 💬 {note}")
        lines.append("")

    unresolved = plan.get("unresolved") or []
    if unresolved:
        lines += ["## 先修环观察区(暂未定序)", ""]
        for node in unresolved:
            cycle = "; ".join(
                f"{e['source']} ⇄ {e['target']}" for e in node.get("cycle_edges", [])
            )
            page_path = str(node.get("page_path") or "").strip()
            label = node.get("label", node["id"])
            title_part = f"[[{page_path}|{label}]]" if page_path else f"**{label}**"
            lines.append(f"- ⚠️ {title_part}{f' · 环: {cycle}' if cycle else ''}")
        lines.append("")

    conflicts = plan.get("edge_conflicts") or []
    if conflicts:
        lines += ["## 先修边冲突(启发式让位于本体边)", ""]
        for conflict in conflicts:
            lines.append(
                f"- {conflict.get('source')} → {conflict.get('target')} · {conflict.get('note', '')}"
            )
        lines.append("")

    removed = plan.get("removed_by_user") or []
    if removed:
        lines += ["## 已按用户要求移除", ""]
        for item in removed:
            lines.append(f"- **{item['label']}** · {item.get('note', '')}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_plan(
    project_id: str,
    user_id: str,
    *,
    reason: str,
    overlay: list[dict] | None = None,
) -> dict:
    """Derive the plan, replay the overlay, and persist it as markdown.

    ``overlay=None`` starts from the currently stored overlay (adjustment path);
    an explicit empty list means a clean rebuild.
    """
    path = plan_file_path(project_id, user_id)
    if overlay is None:
        if path.exists():
            fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            try:
                overlay = json.loads(fm.get("overlay_json") or "[]")
            except json.JSONDecodeError:
                overlay = []
        else:
            overlay = []

    overlay = [op for op in overlay if isinstance(op, dict)]
    prepared = []
    for operation in overlay:
        item = dict(operation)
        item["_node_ids"] = _resolve_ids(
            project_id,
            str(operation.get("node") or "").strip(),
            cluster=bool(operation.get("cluster")),
        )
        if operation.get("op") == "move_before":
            before_ids = _resolve_ids(
                project_id, str(operation.get("before") or "").strip()
            )
            item["_before_id"] = before_ids[0] if len(before_ids) == 1 else ""
        prepared.append(item)

    plan = build_learning_path(project_id, user_id)
    closure = _prereq_closure(project_id)
    report = apply_overlay(plan, prepared, closure=closure)

    generated_at = _iso()
    body = _render_plan_markdown(plan, reason=reason, generated_at=generated_at)
    fingerprints = _fingerprints(project_id, user_id)

    fm = {
        "title": f"学习规划 · {_user_token(project_id, user_id)}",
        "type": "learning_plan",
        "auto_managed": True,
        "user_token": _user_token(project_id, user_id),
        "created": None,
        "updated": generated_at,
        "planner_mode": "react",
        "reason": reason,
        "node_ids": sorted(n["id"] for n in get_nodes(project_id)),
        "graph_fingerprint": fingerprints["graph"],
        "mastery_fingerprint": fingerprints["mastery"],
        "overlay_json": json.dumps(
            [{k: v for k, v in op.items() if not k.startswith("_")} for op in prepared],
            ensure_ascii=False,
        ),
        "adjustment_count": len(prepared),
    }
    if path.exists():
        old_fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        fm["created"] = old_fm.get("created") or generated_at
    else:
        fm["created"] = generated_at

    _atomic_write(path, make_frontmatter(fm) + "\n" + body)

    # Close the loop with the TeachingObject pages: a plan write changes the
    # LearningPlanning class statistics, so re-render those class pages.
    # Best-effort; projection failures never fail the plan write itself.
    try:
        from services.teaching_semantic import refresh_planning_pages

        refresh_planning_pages(project_id)
    except Exception:
        pass

    return {"markdown": body, "plan": plan, "report": report, "path": str(path)}


def read_plan(project_id: str, user_id: str) -> dict | None:
    path = plan_file_path(project_id, user_id)
    if not path.exists():
        return None
    fm, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    return {"frontmatter": fm, "markdown": body, "path": str(path)}


def apply_adjustments(
    project_id: str,
    user_id: str,
    operations: list[dict],
    note: str = "",
) -> dict:
    """Append user operations to the overlay and re-derive the plan.

    The stored overlay plus the new entries are replayed in one ``write_plan``
    pass, so the file, the frontmatter overlay, and the rendered body always
    agree on the same operation history.
    """
    path = plan_file_path(project_id, user_id)
    if not path.exists():
        return {"error": "尚无学习规划,请先调用 rebuild_learning_plan 生成"}

    recorded_at = _iso()
    entries = []
    for operation in operations:
        entry = {k: v for k, v in operation.items() if k in {"op", "node", "before", "note", "cluster"}}
        entry["at"] = recorded_at
        if note:
            entry["request"] = note[:200]
        entries.append(entry)

    fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
    try:
        existing = json.loads(fm.get("overlay_json") or "[]")
    except json.JSONDecodeError:
        existing = []

    result = write_plan(
        project_id,
        user_id,
        reason=f"用户调整({note[:120] or '对话调整'})",
        overlay=existing + entries,
    )

    # The write replays the whole overlay; slice the report down to this
    # round's operations so the caller sees only its own effects.
    start = len(existing)
    this_round = {
        key: [
            entry.get("detail") if "detail" in entry else entry.get("reason")
            for entry in entries_list
            if entry.get("index", 0) >= start
        ]
        for key, entries_list in result["report"].items()
    }
    return {
        "markdown": result["markdown"],
        "plan": result["plan"],
        "report": this_round,
        "applied_operations": entries,
        "path": str(path),
    }
