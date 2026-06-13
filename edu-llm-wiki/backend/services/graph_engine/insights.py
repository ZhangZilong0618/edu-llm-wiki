"""Graph insights: structural + learner-aware.

Two flavours of insight are produced:

* ``generate_insights`` — structural only. Pure function over the graph.
  v2 API. Used by the v2 ``/api/graph/insights`` endpoint.
* ``generate_learner_insights`` — learner-aware. Composes the structural
  output with the learner state summary (8-dim). v3 endpoint.

Insight classes
---------------
* ``knowledge_gap``       — isolated / sparse structural cluster.
* ``bridge``              — multi-community connector.
* ``surprising_connection``— formula/exercise/principle cross-type edge.
* ``frontier``            — prereq-satisfied, not yet opened.
* ``stale``               — content changed since the last exposure.
* ``misconception_cluster``— repeated error tag.
* ``transfer_window``     — A mastered, B unmastered but adjacent.
* ``readiness``           — prereq gap on a stated target node.

Each insight carries ``score``; callers should drop anything below 1.5
(``R7`` in the v3 risk register) to avoid noise.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Sequence


def generate_insights(
    nodes: list[dict],
    edges: list[dict],
    communities: list[dict],
) -> list[dict]:
    """Detect pedagogical signals in a freshly built graph."""
    insights: list[dict] = []

    adjacency: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        adjacency[e["source"]].add(e["target"])
        adjacency[e["target"]].add(e["source"])

    by_id = {n["id"]: n for n in nodes}

    isolated = [n for n in nodes if len(adjacency.get(n["id"], set())) <= 1]
    if isolated:
        insights.append({
            "insight_type": "knowledge_gap",
            "title": f"{len(isolated)} isolated knowledge points",
            "description": "The following concepts have few connections: " + ", ".join(n["label"] for n in isolated[:5]),
            "node_ids": [n["id"] for n in isolated],
            "score": len(isolated) * 0.5,
        })

    for comm in communities:
        if comm.get("cohesion", 0) < 0.15 and comm.get("member_count", 0) >= 3:
            insights.append({
                "insight_type": "knowledge_gap",
                "title": f"Sparse community: {comm.get('label', '')}",
                "description": (
                    f"Cluster with {comm['member_count']} members has low cohesion "
                    f"({comm['cohesion']:.2f})."
                ),
                "node_ids": [],
                "score": (1.0 - float(comm["cohesion"])) * 2,
            })

    community_map: dict[str, int] = {
        n["id"]: int(n["community"]) for n in nodes if int(n.get("community", -1)) >= 0
    }
    for n in nodes:
        nid = n["id"]
        if nid not in community_map:
            continue
        nbr_comms: set[int] = set()
        for nbr in adjacency.get(nid, set()):
            if nbr in community_map:
                nbr_comms.add(community_map[nbr])
        if len(nbr_comms) >= 3:
            insights.append({
                "insight_type": "bridge",
                "title": f"Bridge concept: {n['label']}",
                "description": f"Connects {len(nbr_comms)} different knowledge clusters.",
                "node_ids": [nid],
                "score": len(nbr_comms) * 1.5,
            })

    for e in edges:
        s = by_id.get(e["source"])
        t = by_id.get(e["target"])
        if not s or not t:
            continue
        if s["node_type"] == t["node_type"]:
            continue
        types = {s["node_type"], t["node_type"]}
        if "formula" in types and "principle" in types:
            insights.append({
                "insight_type": "surprising_connection",
                "title": f"Cross-type: {s['label']} <-> {t['label']}",
                "description": f"({s['node_type']} <-> {t['node_type']})",
                "node_ids": [],
                "score": 2.0,
            })

    return insights


def generate_learner_insights(
    nodes: list[dict],
    edges: list[dict],
    communities: list[dict],
    learner_summary: dict,
) -> list[dict]:
    """v3: combine structural insights with the 8-d learner state."""
    out = generate_insights(nodes, edges, communities)

    weak = learner_summary.get("weak_kcs") or []
    for w in weak[:3]:
        out.append({
            "insight_type": "readiness",
            "title": f"Prereq not ready: {w.get('label', w.get('kc_id', ''))}",
            "description": "Probability of mastery is below 0.5. Review prerequisites first.",
            "node_ids": [w.get("kc_id")] if w.get("kc_id") else [],
            "score": 1.8,
        })

    for m in (learner_summary.get("misconception_clusters") or [])[:3]:
        out.append({
            "insight_type": "misconception_cluster",
            "title": f"Frequent error: {m['tag']}",
            "description": f"Seen {m['count']} times. Targeted practice recommended.",
            "node_ids": [],
            "score": float(m.get("count", 1)) * 0.7,
        })

    for w in (learner_summary.get("transfer_windows") or [])[:3]:
        out.append({
            "insight_type": "transfer_window",
            "title": f"Try {w.get('to', '?')}",
            "description": f"You have mastered {w.get('from', '?')}; transferring to {w.get('to', '?')} is likely to help.",
            "node_ids": [w.get("from"), w.get("to")],
            "score": 2.0,
        })

    if (learner_summary.get("overconfidence_gap") or 0) > 0.2:
        out.append({
            "insight_type": "overconfidence",
            "title": "Calibration drift detected",
            "description": "Confidence ratings are running ahead of correctness. Try retrieval practice before re-asserting mastery.",
            "node_ids": [],
            "score": 2.0,
        })

    return [i for i in out if i.get("score", 0) >= 1.5]
