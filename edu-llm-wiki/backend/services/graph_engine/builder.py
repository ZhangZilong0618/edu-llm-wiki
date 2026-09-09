"""Top-level builder that composes the v2 graph.

Keeps the v1 ``build_graph`` / ``get_node_neighborhood`` signatures so the
HTTP layer and search RAG can keep working without churn. Internally it
delegates to the small submodules in this package.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable

from .communities import detect_communities
from .insights import generate_insights
from .parsers import parse_pages, WIKILINK_RE
from .scoring import (
    MAX_GRAPH_DEGREE,
    build_candidate_edges,
    classify_edge,
    finalise_directed_edge,
    prune_edges,
)
from services.graph_store import (
    apply_diff,
    clear_derived_graph,
    ensure_initialised,
    get_edges,
    get_nodes,
    store_communities,
    store_insights,
    upsert_edges,
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


def build_graph(*, project_id: str = "default", force: bool = False) -> dict:
    """Build the v2 learning graph for a project, using the SQLite cache.

    On cache miss the full graph is computed, persisted via :func:`apply_diff`
    and returned. Subsequent calls hit the store directly, so they cost O(N)
    SQLite reads rather than O(N²) Python work.
    """
    ensure_initialised(project_id)
    cached_nodes = get_nodes(project_id)
    cached_edges = get_edges(project_id)
    if cached_nodes and cached_edges and not force:
        return _shape_response(cached_nodes, cached_edges)
    if force:
        clear_derived_graph(project_id)

    pages, title_to_id = parse_pages(project_id=project_id)
    # TODO(legacy): build_candidate_edges expects the v2 split (pages,
    # source_overlap, prereq_pairs, rel_pairs) — fall back to a flat list of
    # candidate edges derived from parsed relationships until the legacy
    # helper is removed.
    candidates = []
    for nid, p in pages.items():
        # 1) Frontmatter `prerequisites` list — `Title` strings resolved via
        #    the title_to_id map.  May be empty for LLM-generated pages
        #    that never emit the field.
        for pre in getattr(p, "prerequisites", []):
            src = title_to_id.get(pre, pre)
            candidates.append({
                "source": src,
                "target": nid,
                "edge_type": "prerequisite",
                "weight": 1.0,
                "origin": "frontmatter",
            })
        # 2) Frontmatter/body “related” titles. These are weaker than
        # explicit prerequisites but are sufficient to connect synthesis,
        # inquiry, and guide pages to their referenced knowledge.
        for rel in getattr(p, "related", []):
            src = title_to_id.get(rel, rel)
            if src == nid:
                continue
            candidates.append({
                "source": nid,
                "target": src,
                "edge_type": "related",
                "weight": 0.8,
                "origin": "related_field",
            })

        # 3) Body wikilinks — for pages whose frontmatter is sparse
        #    (the common case after the v3 ingest pipeline).  The link
        #    direction is *ambiguous* in body text: `数据挖掘` mentioning
        #    `[[机器学习]]` is "related", not necessarily "prerequisite".
        #    Emit a `related` edge so the graph view can still render
        #    the cross-reference, and the frontmatter `prerequisites`
        #    field above remains the authoritative DAG source.
        seen_wikilinks: set[str] = set()
        for raw_link in WIKILINK_RE.findall(getattr(p, "content", "") or ""):
            link = raw_link.split("|", 1)[0].strip()
            if not link or link in seen_wikilinks:
                continue
            seen_wikilinks.add(link)
            src = title_to_id.get(link, link)
            candidates.append({
                "source": src,
                "target": nid,
                "edge_type": "related",
                "weight": 0.7,
                "origin": "wiki_link",
            })
        # 4) Frontmatter `relationships` (LLM-emitted structural edges).
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
    valid_node_ids = set(pages)
    for cand in candidates:
        et = cand.get("edge_type", "related")
        src = cand["source"]
        tgt = cand["target"]
        if src not in valid_node_ids or tgt not in valid_node_ids:
            continue
        edges.append({
            "source": src,
            "target": tgt,
            "edge_type": EDGE_TYPE_ALIASES.get(et, "related"),
            "weight": cand.get("weight", 1.0),
            "origin": cand.get("origin", "inferred"),
            "evidence": cand.get("evidence", ""),
        })

    edges = _break_prerequisite_cycles(edges)
    edges = prune_edges(edges, max_degree=MAX_GRAPH_DEGREE)

    nodes = []
    # Pre-compute degree so node radius reflects how central each concept
    # is in the prerequisite graph. Done once here so Sigma can skip the
    # per-frame computation.
    deg: dict[str, int] = defaultdict(int)
    for e in edges:
        deg[e["source"]] += 1
        deg[e["target"]] += 1
    for p in pages.values():
        degree = deg.get(p.node_id, 0)
        size = max(1, int(round(1.0 + math.log1p(max(degree, 0)) * 1.2)))
        nodes.append({
            "id": p.node_id,
            "label": p.title,
            "node_type": p.page_type,
            "size": size,
            "community": -1,
            "metadata": {
                "path": p.path,
                "bloom_level": p.bloom_level,
                "difficulty": p.difficulty,
                "parent_concept": p.parent_concept,
            },
        })

    communities = detect_communities(edges, nodes)
    # ``detect_communities`` annotates ``community`` (int index) on each node
    # in place; no additional mapping is needed for the response shape.

    apply_diff(project_id)
    # apply_diff rebuilds nodes from the wiki store, but it does not write
    # edges. Persist the edges we just derived (LLM + wiki-link fallback)
    # so the cache-miss read-path sees them.
    if edges:
        upsert_edges(project_id, edges)

    # apply_diff sets degree_in/out to 0 because it runs before the new
    # edges are written (they live in a separate SQLite write). Recompute
    # now that the live edge table reflects reality.
    from services.graph_store import refresh_node_degrees
    refresh_node_degrees(project_id)

    insights = generate_insights(nodes, edges, communities)
    store_communities(project_id, communities)
    store_insights(project_id, insights)
    return _shape_response(nodes, edges, communities=communities, insights=insights)


def _break_prerequisite_cycles(edges: list[dict]) -> list[dict]:
    """Downgrade prerequisite edges that participate in a directed cycle.

    A prerequisite graph must be acyclic. LLM-extracted and wikilink-derived
    prerequisites can occasionally contain cycles; rather than dropping the
    connection, keep it as an undirected ``related`` edge.
    """
    graph: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if edge.get("edge_type") == "prerequisite":
            graph[edge["source"]].add(edge["target"])

    state: dict[str, int] = {}
    cyclic_nodes: set[str] = set()

    def visit(node: str) -> None:
        if state.get(node) == 1:
            cyclic_nodes.add(node)
            return
        if state.get(node) == 2:
            return
        state[node] = 1
        for nxt in graph.get(node, set()):
            visit(nxt)
        state[node] = 2

    for node in list(graph):
        visit(node)

    if not cyclic_nodes:
        return edges

    out: list[dict] = []
    for edge in edges:
        if (
            edge.get("edge_type") == "prerequisite"
            and edge["source"] in cyclic_nodes
            and edge["target"] in cyclic_nodes
        ):
            edge = {**edge, "edge_type": "related", "weight": min(0.8, edge.get("weight", 1.0))}
        out.append(edge)
    return out


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
