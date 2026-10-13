"""System-maintained semantic rendering for TeachingObject class pages.

Class pages were previously stubs ("页面内容可由教师继续补充"). This module
removes the manual-maintenance position: every class page body is now fully
generated and refreshed by the system from two sources:

- ontology semantics — the class label and description plus its group, from
  ``TEACHING_CLASS_LABELS`` / ``TEACHING_CLASS_GROUPS``;
- operational data — per-class instance statistics read from the project's
  SQLite stores (event ledger, assessment cards, BKT mastery, learning plans).

The rendered content lives in a managed block
(``<!-- wiki-auto:ontology-semantic:start/end -->``) that is atomically
replaced in place, so the event projections owned by ``wiki_auto_update``
(snapshots, insights, summaries) are never touched.

Refresh hooks close the loop — the agent acts, the data changes, the page
follows, and the page is readable again through the retrieval tools:

- taxonomy sync (``wiki_store``) renders the block when pages are created;
- every learning event re-renders the block on the pages that event routes to
  (``wiki_auto_update._render_event``);
- learning-plan writes re-render the LearningPlanning pages (``plan_store``).

Rendering is read-only and best-effort: a failing store merely omits its
section and never breaks the event pipeline.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from storage.wiki_store import parse_frontmatter, wiki_path

if TYPE_CHECKING:
    from pathlib import Path

SEMANTIC_START = "<!-- wiki-auto:ontology-semantic:start -->"
SEMANTIC_END = "<!-- wiki-auto:ontology-semantic:end -->"

# The stub text written before pages became system-maintained. It identifies
# legacy empty bodies so the taxonomy sync can retire them.
LEGACY_STUB_BODY = "页面内容可由教师继续补充；系统只维护结构化元数据和事件投影。"

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _class_lock(name: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(name, threading.Lock())


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _taxonomy() -> tuple[dict, dict]:
    from services.ontology_v2 import TEACHING_CLASS_GROUPS, TEACHING_CLASS_LABELS

    return TEACHING_CLASS_GROUPS, TEACHING_CLASS_LABELS


def _class_page_path(project_id: str, class_name: str) -> Path | None:
    groups, _ = _taxonomy()
    for group in groups.values():
        if class_name in tuple(group.get("classes") or ()):
            return wiki_path(project_id) / "teaching" / str(group["folder"]) / f"{class_name}.md"
    return None


# ---------------------------------------------------------------------------
# Per-class operational statistics
# ---------------------------------------------------------------------------

def _event_counts(project_id: str) -> dict[str, int]:
    """Count ledgered learning events per type.

    The durable ledger is ``wiki_update_events`` (owned by the projection
    pipeline in ``wiki_auto_update``), not ``graph_events``.
    """
    from services.graph_store import connect

    try:
        with connect(project_id) as conn:
            rows = conn.execute(
                "SELECT event_type, COUNT(*) AS n FROM wiki_update_events WHERE project_id=? GROUP BY event_type",
                (project_id,),
            ).fetchall()
        return {str(r["event_type"]): int(r["n"]) for r in rows}
    except Exception:
        return {}


_EVENT_LABELS = {
    "dialogue_completed": "对话完成",
    "question_issued": "题目发放",
    "assessment_attempt": "练习完成",
    "review_completed": "复习完成",
    "mastery_change": "掌握更新",
    "learning_event": "学习活动",
}


def _stat_lines_events(class_name: str, counts: dict[str, int]) -> list[str]:
    """Event-driven statistics shared by the event/identity/support groups."""
    relevant: dict[str, int] = {}
    if class_name in {"LearningEvent", "Learner", "LearnerProfile", "ProfileAssertion",
                      "LearningResource", "LearningActivity", "LearningObjective",
                      "KnowledgeCoverageSnapshot", "KnowledgeCoverageRecord"}:
        relevant = dict(counts)
    elif class_name == "DialogueRecord":
        relevant = {"dialogue_completed": counts.get("dialogue_completed", 0)}
    elif class_name == "ExerciseAttempt":
        relevant = {
            "assessment_attempt": counts.get("assessment_attempt", 0),
            "review_completed": counts.get("review_completed", 0),
        }
    if not relevant or not sum(relevant.values()):
        return []
    total = sum(relevant.values())
    parts = " · ".join(
        f"{_EVENT_LABELS.get(key, key)} {value}" for key, value in sorted(relevant.items()) if value
    )
    return [f"- 学习事件总量: **{total}**({parts})"]


def _stat_lines_assessment(project_id: str) -> list[str]:
    from services.graph_store import connect

    try:
        with connect(project_id) as conn:
            questions = conn.execute(
                "SELECT COUNT(*) AS n FROM agent_questions WHERE project_id=?", (project_id,)
            ).fetchone()["n"]
            attempts = conn.execute(
                "SELECT COUNT(*) AS n, AVG(score) AS avg FROM agent_attempts WHERE project_id=?",
                (project_id,),
            ).fetchone()
    except Exception:
        return []
    if not questions:
        # No issued cards yet: omit the section rather than render zeros,
        # matching the event-statistics behaviour.
        return []
    lines = [f"- 服务端题卡: **{int(questions)}** 张"]
    if attempts and int(attempts["n"] or 0):
        avg = float(attempts["avg"] or 0.0)
        lines.append(f"- 作答记录: **{int(attempts['n'])}** 次 · 平均得分 {avg:.2f}")
    return lines


def _stat_lines_mastery(project_id: str) -> list[str]:
    from services.graph_store import connect

    try:
        with connect(project_id) as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS n, AVG(p_known) AS avg,
                          SUM(CASE WHEN p_known >= 0.85 THEN 1 ELSE 0 END) AS mastered
                   FROM bkt_params WHERE project_id=?""",
                (project_id,),
            ).fetchone()
    except Exception:
        return []
    if not row or not int(row["n"] or 0):
        return ["- 尚无掌握度记录(BKT 未开始观测)"]
    avg = float(row["avg"] or 0.0)
    return [
        f"- 被追踪知识单元: **{int(row['n'])}** 个 · 平均掌握度 {avg:.2f}",
        f"- 已过掌握线(≥0.85): **{int(row['mastered'] or 0)}** 个",
    ]


def _stat_lines_planning(project_id: str) -> list[str]:
    plan_dir = wiki_path(project_id) / "learning" / "plan"
    if not plan_dir.exists():
        return ["- 尚无持久化学习规划(对话中请求规划即可生成)"]
    files = sorted(plan_dir.glob("u_*.md"))
    if not files:
        return ["- 尚无持久化学习规划(对话中请求规划即可生成)"]

    total_adjustments = 0
    latest_fm: dict = {}
    latest_mtime = -1.0
    for path in files:
        try:
            frontmatter, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            mtime = path.stat().st_mtime
        except (OSError, ValueError):
            continue
        total_adjustments += int(frontmatter.get("adjustment_count") or 0)
        if mtime > latest_mtime:
            latest_mtime = mtime
            latest_fm = frontmatter

    lines = [f"- 学习者规划: **{len(files)}** 份 · 用户调整累计 {total_adjustments} 次"]
    if latest_fm:
        graph = latest_fm.get("graph_fingerprint") or {}
        mastery = latest_fm.get("mastery_fingerprint") or {}
        lines.append(
            f"- 最新规划: {graph.get('node_count', '?')} 个知识节点 / "
            f"{graph.get('prereq_edge_count', '?')} 条先修关系 · "
            f"已掌握 {mastery.get('mastered_count', 0)} 项 · "
            f"{int(latest_fm.get('adjustment_count') or 0)} 次调整"
        )
        lines.append(f"- 最近更新: {latest_fm.get('updated') or latest_fm.get('created') or '?'}")
    return lines


_GROUP_STATS = {
    "LearningEvents": lambda project_id, class_name, counts: _stat_lines_events(class_name, counts),
    "LearnerIdentity": lambda project_id, class_name, counts: _stat_lines_events(class_name, counts),
    "LearningSupport": lambda project_id, class_name, counts: _stat_lines_events(class_name, counts),
    "AssessmentObjects": lambda project_id, class_name, counts: _stat_lines_assessment(project_id),
    "MasteryTracking": lambda project_id, class_name, counts: _stat_lines_mastery(project_id),
    "LearningPlanning": lambda project_id, class_name, counts: _stat_lines_planning(project_id),
}


# ---------------------------------------------------------------------------
# Rendering and atomic page refresh
# ---------------------------------------------------------------------------

def render_class_semantic(project_id: str, class_name: str) -> str:
    """Render the system-maintained semantic block body for one class."""
    groups, labels = _taxonomy()
    group_name, group_meta = next(
        ((name, meta) for name, meta in groups.items()
         if class_name in tuple(meta.get("classes") or ())),
        (None, None),
    )
    label, description = labels.get(class_name, (class_name, ""))
    group_label = str((group_meta or {}).get("zh") or group_name or "")

    lines = [
        f"## 本体定义 · {label}",
        f"- 本体类: `{class_name}` · 分类: {group_label}(`{group_name}`)",
        f"- 职责: {description}",
    ]

    if group_name in _GROUP_STATS:
        try:
            counts = _event_counts(project_id) if group_name in {
                "LearningEvents", "LearnerIdentity", "LearningSupport"
            } else {}
            stat_lines = _GROUP_STATS[group_name](project_id, class_name, counts)
        except Exception:
            stat_lines = []
        if stat_lines:
            lines.append("")
            lines.append("## 运行数据(系统自动维护)")
            lines.extend(stat_lines)

    lines.append("")
    lines.append(f"- 本节由系统自动渲染与刷新 · {_now_iso()}")
    return "\n".join(lines)


def refresh_class_page(project_id: str, class_name: str) -> bool:
    """Atomically replace the semantic block on one class page.

    Existing event-projection blocks (snapshot/insight/summary) and the
    ontology frontmatter are left untouched. Returns True when the page was
    updated.
    """
    page = _class_page_path(project_id, class_name)
    if page is None or not page.exists():
        return False
    with _class_lock(f"{project_id}:{class_name}"):
        try:
            raw = page.read_text(encoding="utf-8")
            frontmatter, body = parse_frontmatter(raw)
        except (OSError, ValueError):
            return False
        block = f"{SEMANTIC_START}\n{render_class_semantic(project_id, class_name)}\n{SEMANTIC_END}"
        pattern = re.compile(
            rf"{re.escape(SEMANTIC_START)}.*?{re.escape(SEMANTIC_END)}", re.DOTALL
        )
        if pattern.search(body):
            body = pattern.sub(block, body, count=1)
        else:
            body = body.rstrip() + "\n\n" + block + "\n"
        from storage.wiki_store import make_frontmatter

        tmp = page.with_name(f".{page.name}.{threading.get_ident()}.tmp")
        tmp.write_text(make_frontmatter(frontmatter) + "\n" + body.strip() + "\n", encoding="utf-8")
        tmp.replace(page)
    return True


def refresh_classes(project_id: str, class_names: list[str] | tuple[str, ...]) -> None:
    """Best-effort refresh for several class pages; failures are skipped."""
    for class_name in class_names:
        try:
            refresh_class_page(project_id, class_name)
        except Exception:
            continue


def refresh_planning_pages(project_id: str) -> None:
    """Refresh the LearningPlanning group pages after a plan write."""
    refresh_classes(project_id, ("LearningPath", "LearningPathStep", "PathAdjustmentRecord"))
