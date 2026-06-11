"""Top-level builder that composes the v2 graph.

Keeps the v1 ``build_graph`` / ``get_node_neighborhood`` signatures so the
HTTP layer and search RAG can keep working without churn. Internally it
delegates to the small submodules in this package.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .communities import detect_communities
from .insights import generate_insights
from .parsers import parse_pages
from .scoring import (
    MAX_GRAPH_DEGREE,
    build_candidate_edges,
    classify_edge,
    finalise_directed_edge,
    prune_edges,
)
from services.graph_store import (
    apply_diff,
    ensure_initialised,
    get_edges,
    get_nodes,
)

# Maps the v1 edge-type vocabulary to the v2 taxonomy used by Pydantic + UI.
EDGE_TYPE_ALIASES = {
    "prerequisite": "prerequisite",
    "direct": "related",        # the v1 "direct" is a stronger "related"
    "source": "related",
    "related": "related",
    "teaches": "teaches",
    "enables": "enables",
    "scaffolds": "scaffolds",
    "applies_to": "applies_to",
    "derives": "derives",
}


def build_graph(*, project_id: str = "default") -> dict:
    """Build the v2 learning graph for a project, using the SQLite cache.

    On cache miss the full graph is computed, persisted via :func:`apply_diff`
    and returned. Subsequent calls hit the store directly, so they cost O(N)
    SQLite reads rather than O(N²) Python work.
    """
    ensure_initialised(project_id)
    cached_nodes = get_nodes(project_id)
    cached_edges = get_edges(project_id)
    if cached_nodes and cached_edges:
        return _shape_response(cached_nodes, cached_edges)

    pages, title_to_id = parse_pages(project_id=project_id)
    # TODO(legacy): build_candidate_edges expects the v2 split (pages,
    # source_overlap, prereq_pairs, rel_pairs) — fall back to a flat list of
    # candidate edges derived from parsed relationships until the legacy
    # helper is removed.
    candidates = []
    for nid, p in pages.items():
        for r in getattr(p, "relationships", []):
            candidates.append({
                "source": title_to_id.get(r.src, r.src),
                "target": title_to_id.get(r.dst, r.dst),
                "edge_type": r.rel_type,
                "weight": 1.0,
                "origin": "llm",
                "evidence": r.description or "",
            })

    edges: list[dict] = []
    for cand in candidates:
        et = cand.get("edge_type", "related")
        src = cand["source"]
        tgt = cand["target"]
        edges.append({
            "source": src,
            "target": tgt,
            "edge_type": EDGE_TYPE_ALIASES.get(et, "related"),
            "weight": cand.get("weight", 1.0),
        })

    edges = prune_edges(edges, max_degree=MAX_GRAPH_DEGREE)

    nodes = []
    for p in pages.values():
        nodes.append({
            "id": p.node_id,
            "label": p.title,
            "node_type": p.page_type,
            "size": 1,
            "community": -1,
            "metadata": {
                "path": p.path,
                "bloom_level": p.bloom_level,
                "difficulty": p.difficulty,
                "parent_concept": p.parent_concept,
            },
        })

    communities = detect_communities(edges, nodes)
    community_map = {n["id"]: i for i, comm in enumerate(communities) for n in comm}
    for node in nodes:
        node["community"] = community_map.get(node["id"], -1)

    apply_diff(project_id, nodes=nodes, edges=edges)

    insights = generate_insights(nodes, edges, communities)
    return _shape_response(nodes, edges, communities=communities, insights=insights)


def get_node_neighborhood(node_id: str, depth: int = 1, *, project_id: str = "default") -> dict:
    """Return a node and its neighbours up to ``depth`` hops.

    Reads the cached graph from the store; falls back to :func:`build_graph`
    on cache miss. The returned payload only carries nodes/edges; the
    community + insight fields are omitted because neighbourhoods are
    small and the client does not need the global context.
    """
    ensure_initialised(project_id)
    data = build_graph(project_id=project_id)
    nodes_by_id = {n["id"]: n for n in data["nodes"]}
    if node_id not in nodes_by_id:
        return {"nodes": [], "edges": []}

    visited = {node_id}
    frontier = {node_id}
    nb_nodes = [nodes_by_id[node_id]]
    nb_edges: list[dict] = []

    for _ in range(depth):
        next_frontier: set[str] = set()
        for e in data["edges"]:
            if e["source"] in frontier and e["target"] not in visited:
                next_frontier.add(e["target"])
                nb_edges.append(e)
                if e["target"] in nodes_by_id:
                    nb_nodes.append(nodes_by_id[e["target"]])
            elif e["target"] in frontier and e["source"] not in visited:
                next_frontier.add(e["source"])
                nb_edges.append(e)
                if e["source"] in nodes_by_id:
                    nb_nodes.append(nodes_by_id[e["source"]])
        visited.update(next_frontier)
        frontier = next_frontier
    return {"nodes": nb_nodes, "edges": nb_edges}


def _shape_response(
    nodes: list[dict],
    edges: list[dict],
    communities: list[dict] | None = None,
    insights: list[dict] | None = None,
) -> dict:
    return {
        "nodes": nodes,
        "edges": edges,
        "communities": communities or [],
        "insights": insights or [],
    }
