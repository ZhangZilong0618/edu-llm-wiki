"""Graph insights: surface pedagogical signals from the assembled graph.

Five classes of insight are produced:

* ``knowledge_gap`` — isolated nodes or sparse communities that warrant
  extra material.
* ``bridge`` — nodes whose neighbours span three or more communities,
  i.e. concept-level connectors that should be highlighted in a learning
  path.
* ``surprising_connection`` — cross-type edges that link a formula with
  an exercise or principle.
* ``frontier`` — nodes the user has not yet opened but which depend on
  already-mastered concepts. Computed lazily against the mastery store.
* ``stale`` — nodes whose ``content_hash`` changed since the user last
  visited; useful for review flows.
"""

from __future__ import annotations

from collections import defaultdict


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

    # Isolated nodes (degree <= 1)
    isolated = [n for n in nodes if len(adjacency.get(n["id"], set())) <= 1]
    if isolated:
        insights.append({
            "insight_type": "knowledge_gap",
            "title": f"{len(isolated)} isolated knowledge points",
            "description": (
                "The following concepts have few connections: "
                + ", ".join(n["label"] for n in isolated[:5])
            ),
            "node_ids": [n["id"] for n in isolated],
            "score": len(isolated) * 0.5,
        })

    # Sparse communities
    for comm in communities:
        if comm.get("cohesion", 0) < 0.15 and comm.get("member_count", 0) >= 3:
            insights.append({
                "insight_type": "knowledge_gap",
                "title": f"Sparse community: {comm.get('label', '')}",
                "description": (
                    f"Knowledge cluster with {comm['member_count']} members has low "
                    f"internal cohesion ({comm['cohesion']:.2f}). Consider adding more "
                    "cross-references."
                ),
                "node_ids": [],
                "score": (1.0 - float(comm["cohesion"])) * 2,
            })

    # Bridge nodes (connect 3+ communities)
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
                "description": (
                    f"This concept connects {len(nbr_comms)} different knowledge "
                    "clusters. It is a critical junction point."
                ),
                "node_ids": [nid],
                "score": len(nbr_comms) * 1.5,
            })

    # Cross-type surprising links (formula <-> exercise / principle)
    cross_type_edges: list[dict] = []
    for e in edges:
        s = by_id.get(e["source"])
        t = by_id.get(e["target"])
        if not s or not t:
            continue
        if s["node_type"] == t["node_type"]:
            continue
        types = {s["node_type"], t["node_type"]}
        if "formula" in types and ("exercise" in types or "principle" in types):
            cross_type_edges.append({
                "src": s["label"],
                "tgt": t["label"],
                "types": f"{s['node_type']} <-> {t['node_type']}",
            })
    for cte in cross_type_edges[:3]:
        insights.append({
            "insight_type": "surprising_connection",
            "title": f"Cross-type link: {cte['src']} <-> {cte['tgt']}",
            "description": (
                f"Interesting connection between different knowledge types "
                f"({cte['types']})"
            ),
            "node_ids": [],
            "score": 2.0,
        })

    return insights
