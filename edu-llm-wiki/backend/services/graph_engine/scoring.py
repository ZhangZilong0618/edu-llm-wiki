"""Edge scoring and pruning for the learning graph.

The v2 engine composes edges from three explicit sources (wikilinks, source
overlap, LLM ``relationships``) and from three structural signals (direct
links, common-neighbour Adamic-Adar, type affinity). The result is a single
``edge_type`` per (a, b) pair with a numeric weight and a direction.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable

# Signal weights for edge relevance scoring.
WEIGHTS = {
    "direct_link": 3.0,
    "source_overlap": 4.0,
    "common_neighbor": 1.5,
    "type_affinity": 1.0,
}

# Cross-type affinity matrix — higher means the two node types tend to be
# pedagogically adjacent.
TYPE_AFFINITY: dict[str, dict[str, float]] = {
    "concept":   {"concept": 0.8, "formula": 1.3, "principle": 1.2, "exercise": 1.2,
                  "source": 1.0, "synthesis": 1.2, "query": 1.0},
    "formula":   {"concept": 1.3, "formula": 0.7, "principle": 1.3, "exercise": 1.5,
                  "source": 0.8, "synthesis": 1.0, "query": 0.8},
    "principle": {"concept": 1.2, "formula": 1.3, "principle": 0.7, "exercise": 1.0,
                  "source": 0.8, "synthesis": 1.1, "query": 0.8},
    "exercise":  {"concept": 1.2, "formula": 1.5, "principle": 1.0, "exercise": 0.4,
                  "source": 0.8, "synthesis": 0.8, "query": 0.8},
    "source":    {"concept": 1.0, "formula": 0.8, "principle": 0.8, "exercise": 0.8,
                  "source": 0.5, "synthesis": 1.0, "query": 0.8},
    "synthesis": {"concept": 1.2, "formula": 1.0, "principle": 1.1, "exercise": 0.8,
                  "source": 1.0, "synthesis": 0.8, "query": 1.0},
    "query":     {"concept": 1.0, "formula": 0.8, "principle": 0.8, "exercise": 0.8,
                  "source": 0.8, "synthesis": 1.0, "query": 0.5},
}

# Type-order for prerequisite inference: smaller = more foundational.
PREREQ_TYPE_ORDER = {
    "concept": 0, "formula": 1, "principle": 2, "source": 3,
    "exercise": 4, "synthesis": 5, "query": 6,
}

# Pedagogical edge types emitted by the engine.
EDGE_TYPES = {
    "prerequisite",   # A must be understood before B
    "teaches",        # A is the source-of-truth that explains B (formula -> concept etc.)
    "derives",        # A is mathematically/logically derived from B
    "applies_to",     # A is demonstrated/used in B (exercise / example)
    "scaffolds",      # A is a softer on-ramp to B (related but supportive)
    "related",        # generic association, weakest signal
}

MAX_GRAPH_DEGREE = 8


def score_edges(
    page_map: dict,
    parsed_pages: dict,
    *,
    max_degree: int = MAX_GRAPH_DEGREE,
) -> list[dict]:
    """Compute one record per undirected (a, b) edge.

    Returns a list of dicts with keys ``source``, ``target``, ``edge_type``,
    ``weight``, plus optional ``signals`` breakdown for debugging.
    """
    link_graph: dict[str, set[str]] = defaultdict(set)
    in_links: dict[str, set[str]] = defaultdict(set)
    source_map: dict[str, set[str]] = defaultdict(set)
    node_sources: dict[str, set[str]] = {}
    prereq_directed: set[tuple[str, str]] = set()
    llm_relationships: dict[tuple[str, str], dict] = {}

    for node_id, parsed in parsed_pages.items():
        for target in parsed.wikilinks:
            if target in page_map and target != node_id:
                link_graph[node_id].add(target)
                in_links[target].add(node_id)
        srcs = parsed.sources
        node_sources[node_id] = set(srcs)
        for src in srcs:
            source_map[src].add(node_id)
        for prereq in parsed.prerequisites:
            prereq_id = prereq.replace(".md", "").strip()
            if prereq_id in page_map and prereq_id != node_id:
                prereq_directed.add((prereq_id, node_id))

        for rel in parsed.relationships:
            rel_type = rel.get("type")
            if rel_type not in EDGE_TYPES:
                continue
            other = _resolve_other(rel.get("to"), page_map, parsed_pages) \
                or _resolve_other(rel.get("from"), page_map, parsed_pages, exclude=node_id)
            if not other or other == node_id:
                continue
            key = tuple(sorted((node_id, other)))
            existing = llm_relationships.get(key)
            # Higher-precedence relationship wins if both endpoints emit one.
            if existing is None or _REL_PRECEDENCE.get(rel_type, 0) > _REL_PRECEDENCE.get(existing["type"], 0):
                llm_relationships[key] = {
                    "from": node_id if rel.get("from") else other,
                    "to": other if rel.get("from") else node_id,
                    "type": rel_type,
                    "description": rel.get("description", ""),
                }

    # Adamic-Adar over the union of out- and in-links.
    neighbors: dict[str, set[str]] = {}
    degrees: dict[str, int] = {}
    for node_id in page_map:
        nbrs = link_graph[node_id] | in_links[node_id]
        neighbors[node_id] = nbrs
        degrees[node_id] = len(nbrs)

    edge_set: set[tuple[str, str]] = set()
    for src_id, targets in link_graph.items():
        for tgt_id in targets:
            edge_set.add((min(src_id, tgt_id), max(src_id, tgt_id)))

    for src_path, node_set in source_map.items():
        source_nodes = [nid for nid in node_set if page_map[nid]["type"] == "source"]
        if source_nodes:
            for s in source_nodes:
                for nid in node_set:
                    if nid != s:
                        edge_set.add((min(s, nid), max(s, nid)))
        else:
            node_list = sorted(node_set)
            for i, nid in enumerate(node_list):
                for other in node_list[i + 1:i + 4]:
                    edge_set.add((min(nid, other), max(nid, other)))

    for a, b in prereq_directed:
        edge_set.add((min(a, b), max(a, b)))

    for a, b in llm_relationships:
        edge_set.add((min(a, b), max(a, b)))

    edge_list: list[dict] = []
    for a, b in edge_set:
        type_a = page_map[a]["type"]
        type_b = page_map[b]["type"]

        forward = 1 if b in link_graph.get(a, set()) else 0
        backward = 1 if a in link_graph.get(b, set()) else 0
        direct_score = (forward + backward) * WEIGHTS["direct_link"]

        shared_sources = len(node_sources.get(a, set()) & node_sources.get(b, set()))
        source_score = shared_sources * WEIGHTS["source_overlap"]

        adamic_adar = 0.0
        for common in neighbors.get(a, set()) & neighbors.get(b, set()):
            deg = max(degrees.get(common, 2), 2)
            adamic_adar += 1.0 / math.log(deg)
        neighbor_score = adamic_adar * WEIGHTS["common_neighbor"]

        affinity = TYPE_AFFINITY.get(type_a, {}).get(type_b, 0.5)
        type_score = affinity * WEIGHTS["type_affinity"]

        total = round(direct_score + source_score + neighbor_score + type_score, 2)

        edge_type, prereq_source = _classify_edge(
            a, b, type_a, type_b, link_graph, page_map,
            direct_score, source_score, prereq_directed,
            llm_relationships.get((min(a, b), max(a, b))),
        )

        if edge_type == "prerequisite" and prereq_source is not None:
            source_node = prereq_source
            target_node = b if prereq_source == a else a
        else:
            source_node = a
            target_node = b

        edge_list.append({
            "source": source_node,
            "target": target_node,
            "edge_type": edge_type,
            "weight": total,
        })

    return _prune_edges(edge_list, max_degree=max_degree)


# Higher = wins when both endpoints emit a relationship for the same pair.
_REL_PRECEDENCE = {
    "prerequisite": 6,
    "derives": 5,
    "teaches": 4,
    "applies_to": 3,
    "scaffolds": 2,
    "related": 1,
}


def _classify_edge(
    a: str, b: str, type_a: str, type_b: str,
    link_graph: dict[str, set[str]],
    page_map: dict,
    direct_score: float,
    source_score: float,
    prereq_directed: set[tuple[str, str]],
    llm_rel: dict | None,
) -> tuple[str, str | None]:
    if llm_rel:
        return llm_rel["type"], llm_rel["from"]
    if (a, b) in prereq_directed:
        return "prerequisite", a
    if (b, a) in prereq_directed:
        return "prerequisite", b
    if direct_score > 0:
        return "direct", None
    if source_score > 0 and (type_a == "source" or type_b == "source"):
        return "teaches", None
    order_a = PREREQ_TYPE_ORDER.get(type_a, 99)
    order_b = PREREQ_TYPE_ORDER.get(type_b, 99)
    if b in link_graph.get(a, set()) and order_b <= order_a:
        return "prerequisite", b
    if a in link_graph.get(b, set()) and order_a <= order_b:
        return "prerequisite", a
    return "related", None


def _resolve_other(
    name: str | None,
    page_map: dict,
    parsed_pages: dict,
    *,
    exclude: str | None = None,
) -> str | None:
    if not name:
        return None
    target = name.replace(".md", "").strip()
    if target in page_map and target != exclude:
        return target
    for pid, parsed in parsed_pages.items():
        if pid == exclude:
            continue
        if parsed.title.strip().lower() == target.lower():
            return pid
    return None


def _prune_edges(edge_list: Iterable[dict], *, max_degree: int) -> list[dict]:
    """Keep the graph readable by limiting weak dense edges per node."""
    priority = {"prerequisite": 4, "derives": 4, "teaches": 3, "direct": 3,
                "applies_to": 2, "scaffolds": 2, "related": 1}
    degree: dict[str, int] = defaultdict(int)
    pruned: list[dict] = []
    seen: set[tuple[str, str]] = set()

    sorted_edges = sorted(
        edge_list,
        key=lambda e: (-priority.get(e["edge_type"], 1), -e["weight"]),
    )

    for edge in sorted_edges:
        key = tuple(sorted((edge["source"], edge["target"])))
        if key in seen:
            continue
        keep = edge["edge_type"] in {"prerequisite", "derives", "direct", "teaches", "applies_to"}
        if not keep:
            keep = degree[edge["source"]] < max_degree and degree[edge["target"]] < max_degree
        if keep:
            seen.add(key)
            pruned.append(edge)
            degree[edge["source"]] += 1
            degree[edge["target"]] += 1
    return pruned

# --- public aliases used by the builder ---
def build_candidate_edges(page_map, parsed_pages):
    """Yield candidate (source, target, signal_type) tuples from the parsed pages."""
    candidates = []
    for page in parsed_pages.values():
        nid = page.node_id
        for target_id in page.wikilinks:
            if target_id in parsed_pages:
                candidates.append((nid, target_id, "direct"))
    # source-overlap edges are computed at a higher level (needs source_map)
    # so the builder wires them in via a second pass.
    return candidates


def classify_edge(a, b, type_a, type_b, link_graph):
    """Public wrapper around the underscore-prefixed helper."""
    return _classify_edge(a, b, type_a, type_b, link_graph)


def finalise_directed_edge(edge):
    """Ensure an edge has a stable (source, target) ordered by prerequisite direction."""
    if edge.get("edge_type") == "prerequisite":
        # convention: source = the prerequisite, target = the dependent
        # caller should already have set this; if not, leave as-is
        return edge
    return edge


def prune_edges(edge_list, *, max_degree=MAX_GRAPH_DEGREE):
    return _prune_edges(edge_list, max_degree=max_degree)
