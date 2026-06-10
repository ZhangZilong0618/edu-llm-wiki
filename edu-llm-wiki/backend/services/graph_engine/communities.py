"""Community detection using the Louvain algorithm.

Falls back to a deterministic label-propagation strategy when networkx is
not available, so the rest of the engine never sees a half-built graph.
"""

from __future__ import annotations

from collections import defaultdict

try:
    import networkx as nx
    from networkx.algorithms.community import louvain_communities
    HAS_NETWORKX = True
except ImportError:  # pragma: no cover
    HAS_NETWORKX = False


def detect_communities(edges: list[dict], nodes: list[dict]) -> list[dict]:
    """Run Louvain on the undirected projection of ``edges``.

    Returns ``[{id, label, cohesion, member_count, top_node}]``. Falls back to
    label propagation when networkx is missing.
    """
    if not nodes:
        return []

    if HAS_NETWORKX and edges:
        g = nx.Graph()
        for n in nodes:
            g.add_node(n["id"])
        for e in edges:
            g.add_edge(e["source"], e["target"], weight=e.get("weight", 1.0))
        try:
            communities = louvain_communities(g, weight="weight", seed=42)
        except Exception:
            communities = _label_propagation(nodes, edges)
    else:
        communities = _label_propagation(nodes, edges)

    # Annotate community membership on the node dicts (in place) so the rest
    # of the builder can include ``community`` in the response.
    by_id = {n["id"]: n for n in nodes}
    out: list[dict] = []
    for idx, members in enumerate(communities):
        member_ids = sorted(members)
        for mid in member_ids:
            if mid in by_id:
                by_id[mid]["community"] = idx
        # Internal edge density / possible = (k*(k-1)/2)
        k = len(member_ids)
        possible = max(1, k * (k - 1) / 2)
        internal = 0
        for e in edges:
            if e["source"] in members and e["target"] in members:
                internal += 1
        cohesion = internal / possible if possible else 0.0
        top_node = _top_node(member_ids, nodes)
        out.append({
            "id": idx,
            "label": f"Cluster {idx + 1}",
            "cohesion": round(cohesion, 3),
            "member_count": k,
            "top_node": top_node,
        })
    # Ensure every node has a community (unassigned -> -1)
    for n in nodes:
        n.setdefault("community", -1)
    return out


def _top_node(member_ids: list[str], nodes: list[dict]) -> str:
    by_id = {n["id"]: n for n in nodes}
    best = member_ids[0]
    best_size = 0
    for mid in member_ids:
        node = by_id.get(mid)
        if not node:
            continue
        size = int(node.get("size", 1))
        if size > best_size:
            best_size = size
            best = mid
    return best


def _label_propagation(nodes: list[dict], edges: list[dict]) -> list[set[str]]:
    """Deterministic community detection without networkx.

    Each node starts with its own label and iteratively adopts the most
    frequent label among its neighbours until stable.
    """
    labels: dict[str, int] = {n["id"]: i for i, n in enumerate(nodes)}
    neighbours: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        neighbours[e["source"]].append(e["target"])
        neighbours[e["target"]].append(e["source"])
    # Cap iterations to avoid pathological cases.
    for _ in range(20):
        changed = False
        for nid in list(labels.keys()):
            counts: dict[int, int] = defaultdict(int)
            for nbr in neighbours.get(nid, []):
                if nbr in labels:
                    counts[labels[nbr]] += 1
            if not counts:
                continue
            best_label = max(counts.items(), key=lambda kv: kv[1])[0]
            if best_label != labels[nid]:
                labels[nid] = best_label
                changed = True
        if not changed:
            break
    buckets: dict[int, set[str]] = defaultdict(set)
    for n, l in labels.items():
        buckets[l].add(n)
    return [s for s in buckets.values() if s]