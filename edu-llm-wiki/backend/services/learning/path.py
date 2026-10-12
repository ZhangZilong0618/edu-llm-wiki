"""学习路径 —— 拓扑分层视图(重设计)。

路径 = f(图, 掌握度) 的纯函数,不落库、不快照:
- 定序边 = prerequisiteOf(本体先修,优先) + prerequisite(启发式):
  两套边方向可能冲突(实测合并会成环),增量建 DAG——本体边优先
  接受,与之成环的启发式边拒绝并进 edge_conflicts 观察区;
- Kahn 分层:入度 0 的全部点进第 1 层(含孤立点),剥离后下一批进
  第 2 层……同层 = 并列可学,顺序自由(层间推荐不硬锁);
- BKT p_known(bkt_params 表,阈值 0.85)给每点标状态:
    mastered   自身 p_known ≥ 0.85
    ready      未掌握且直接先修全部 mastered(无先修也算 ready)
    upcoming   存在未掌握的直接先修

BKT 本体(services/learning/bkt.py、services/mastery.py)只读不写:
本模块是掌握度的消费者。图重建后重算即得新路径;本体教学层的
LearningPath/PathAdjustmentRecord 快照留待 ABox 阶段。
"""

from __future__ import annotations

from collections import defaultdict

from services.graph_store import get_edges, get_nodes

#: 定序边:启发式先修 + 本体 prerequisiteOf
PREREQ_EDGE_TYPES = {"prerequisite", "prerequisiteOf"}

#: 掌握阈值(与 mastery 体系一致)
MASTERY_THRESHOLD = 0.85


def _list_bkt(project_id: str, user_id: str) -> dict[str, float]:
    """批量读取 BKT p_known:{kc_id -> p_known}。"""
    from services.graph_store import connect

    with connect(project_id) as conn:
        rows = conn.execute(
            "SELECT kc_id, p_known FROM bkt_params WHERE project_id=? AND user_id=?",
            (project_id, user_id),
        ).fetchall()
    return {str(r["kc_id"]): float(r["p_known"]) for r in rows}


#: 边优先级:本体关系(正式、经校验) > 启发式(frontmatter 推测)。
#: 增量建 DAG:低优先级边若与已接受边成环则拒绝,并进冲突清单。
_EDGE_PRIORITY = {"ontology": 0, "frontmatter": 1}


def _reaches(adj: dict, start: str, goal: str) -> bool:
    """start 是否可达 goal(DFS)。"""
    stack, seen = [start], {start}
    while stack:
        node = stack.pop()
        if node == goal:
            return True
        for nxt in adj.get(node, []):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False


def _prereq_graph(project_id: str) -> tuple[dict, dict, list[dict], list[dict]]:
    """返回 (邻接表, 入度表, 接受的定序边, 被拒冲突边)。

    本体 prerequisiteOf 与启发式 prerequisite 的方向可能不一致
    (实测:单独各自无环,合并成环)。增量建图:按优先级接受边,
    会成环的低优先级边拒绝并记录——本体方向赢,冲突可观察。
    """
    nodes = get_nodes(project_id)
    edges = get_edges(project_id)
    node_ids = {n["id"] for n in nodes}
    candidates = sorted(
        (
            e
            for e in edges
            if e.get("edge_type") in PREREQ_EDGE_TYPES
            and e["source"] in node_ids
            and e["target"] in node_ids
            and e["source"] != e["target"]
        ),
        key=lambda e: _EDGE_PRIORITY.get(e.get("origin", ""), 9),
    )

    adj: dict[str, list[str]] = defaultdict(list)
    indeg: dict[str, int] = defaultdict(int)
    accepted: list[dict] = []
    rejected: list[dict] = []
    for e in candidates:
        src, tgt = e["source"], e["target"]
        if tgt in adj[src]:  # 同对重复
            continue
        if _reaches(adj, tgt, src):  # tgt ⇝ src 已存在,加 src→tgt 成环
            rejected.append(e)
            continue
        adj[src].append(tgt)
        indeg[tgt] += 1
        accepted.append(e)
    return adj, indeg, accepted, rejected


def _kahn_levels(adj: dict, indeg: dict, node_ids: set[str]) -> tuple[list[list[str]], list[str]]:
    """Kahn 分层拓扑排序。返回 (每层节点列表, 未定序节点)。

    环上的节点永远剥不掉 → 进未定序列表(观察模式)。
    """
    remaining_indeg = dict(indeg)
    current = sorted(n for n in node_ids if remaining_indeg.get(n, 0) == 0)
    levels: list[list[str]] = []
    placed: set[str] = set()
    while current:
        levels.append(current)
        placed.update(current)
        nxt: set[str] = set()
        for src in current:
            for tgt in adj.get(src, []):
                remaining_indeg[tgt] -= 1
                if remaining_indeg[tgt] == 0:
                    nxt.add(tgt)
        current = sorted(nxt)
    unresolved = sorted(n for n in node_ids if n not in placed)
    return levels, unresolved


def build_learning_path(project_id: str, user_id: str = "default") -> dict:
    """学习路径主入口:分层拓扑 + BKT 状态覆盖。"""
    nodes = get_nodes(project_id)
    node_map = {n["id"]: n for n in nodes}
    if not node_map:
        return {
            "project_id": project_id,
            "learner": user_id,
            "progress": {"mastered": 0, "total": 0, "current_level": 0},
            "levels": [],
            "unresolved": [],
            "edge_conflicts": [],
        }

    adj, indeg, prereq_edges, rejected_edges = _prereq_graph(project_id)
    levels, unresolved_ids = _kahn_levels(adj, indeg, set(node_map))

    # 直接先修表 + 被依赖数
    direct_prereqs: dict[str, list[str]] = defaultdict(list)
    dependents: dict[str, int] = defaultdict(int)
    for e in prereq_edges:
        direct_prereqs[e["target"]].append(e["source"])
        dependents[e["source"]] += 1

    bkt = _list_bkt(project_id, user_id)

    def p_known(nid: str) -> float | None:
        return bkt.get(nid)

    def status(nid: str) -> str:
        if (bkt.get(nid) is not None and bkt[nid] >= MASTERY_THRESHOLD):
            return "mastered"
        if all(
            bkt.get(p) is not None and bkt[p] >= MASTERY_THRESHOLD
            for p in direct_prereqs.get(nid, [])
        ):
            return "ready"
        return "upcoming"

    def node_obj(nid: str, level: int | None = None) -> dict:
        n = node_map[nid]
        prereq_ids = sorted(direct_prereqs.get(nid, []))
        return {
            "id": nid,
            "label": n.get("label", ""),
            "node_type": n.get("node_type", "unknown"),
            "page_path": (n.get("metadata") or {}).get("path", ""),
            "level": level,
            "p_known": p_known(nid),
            "attempts": None,  # 由 node_mastery 补充的成本高;BKT 观测数足够
            "status": status(nid),
            "prereq_ids": prereq_ids,
            "prereq_labels": [node_map[p].get("label", p) for p in prereq_ids],
            "dependents_count": dependents.get(nid, 0),
        }

    level_objs = [
        {"level": i + 1, "nodes": [node_obj(nid, level=i + 1) for nid in ids]}
        for i, ids in enumerate(levels)
    ]

    # 环点:附上参与环的定序边(两端都在未定序集合内)
    unresolved_set = set(unresolved_ids)
    cycle_edges = [
        e for e in prereq_edges if e["source"] in unresolved_set and e["target"] in unresolved_set
    ]
    unresolved_objs = [node_obj(nid) for nid in unresolved_ids]
    for obj in unresolved_objs:
        obj["status"] = "unresolved"
        obj["cycle_edges"] = [
            {
                "source": node_map[e["source"]].get("label", e["source"]),
                "target": node_map[e["target"]].get("label", e["target"]),
            }
            for e in cycle_edges
            if e["source"] == obj["id"] or e["target"] == obj["id"]
        ]

    # 进度与当前层:最早含未掌握点的层
    mastered = sum(1 for n in node_map if status(n) == "mastered")
    current_level = 0
    for lv in level_objs:
        if any(n["status"] != "mastered" for n in lv["nodes"]):
            current_level = lv["level"]
            break
    if current_level == 0 and level_objs:
        current_level = level_objs[-1]["level"]

    # 当前焦点:最早层里第一个未掌握的 ready 点
    focus_id = None
    for lv in level_objs:
        for n in lv["nodes"]:
            if n["status"] == "ready":
                focus_id = n["id"]
                break
        if focus_id:
            break

    # 边冲突观察区:被拒的启发式先修边(与本体方向不一致,本体赢)
    edge_conflicts = [
        {
            "source": node_map[e["source"]].get("label", e["source"]),
            "target": node_map[e["target"]].get("label", e["target"]),
            "origin": e.get("origin", ""),
            "note": "与已接受的本体先修方向成环,已让位于本体边",
        }
        for e in rejected_edges
    ]

    return {
        "project_id": project_id,
        "learner": user_id,
        "mastery_threshold": MASTERY_THRESHOLD,
        "progress": {
            "mastered": mastered,
            "total": len(node_map),
            "current_level": current_level,
        },
        "focus_id": focus_id,
        "levels": level_objs,
        "unresolved": unresolved_objs,
        "edge_conflicts": edge_conflicts,
    }


def point_context_pages(node_id: str, project_id: str = "default") -> tuple[list[str], str | None]:
    """出题上下文的页面路径:[本点页面, 直接先修点页面...]。

    返回 (paths, label);label 供测试标题兜底。
    """
    nodes = get_nodes(project_id)
    node_map = {n["id"]: n for n in nodes}
    node = node_map.get(node_id)
    if not node:
        return [], None
    _, _, prereq_edges, _rejected = _prereq_graph(project_id)
    prereq_ids = sorted(
        {e["source"] for e in prereq_edges if e["target"] == node_id}
    )
    paths = []
    for nid in [node_id, *prereq_ids]:
        n = node_map.get(nid)
        p = (n.get("metadata") or {}).get("path", "")
        if p:
            paths.append(p)
    return paths, node.get("label")
