"""Knowledge Graph Engine.

Builds a graph from wiki pages:
- Nodes: concepts, formulas, principles, courses, sources
- Edges: 4-signal relevance scoring (direct links, source overlap,
  Adamic-Adar common neighbors, type affinity)
- Community detection: Louvain algorithm
- Graph insights: isolated nodes, bridges, surprising connections
"""

import math
import re
from collections import defaultdict

from storage.wiki_store import list_wiki_pages, parse_frontmatter, wiki_path

try:
    import networkx as nx
    from networkx.algorithms.community import louvain_communities
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False


WIKILINK_RE = re.compile(r'\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]')

# Signal weights for edge relevance scoring
WEIGHTS = {
    "direct_link": 3.0,
    "source_overlap": 4.0,
    "common_neighbor": 1.5,
    "type_affinity": 1.0,
}

# Cross-type affinity: higher = stronger connection between types
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


PREREQ_TYPE_ORDER = {"concept": 0, "formula": 1, "principle": 2, "source": 3, "exercise": 4, "synthesis": 5, "query": 6}


def build_graph(*, project_id: str = "default") -> dict:
    """Build the knowledge graph with 4-signal edge relevance scoring."""
    nodes = []
    pages = list_wiki_pages(project_id=project_id)
    wp = wiki_path(project_id)

    # Build node id -> page info
    page_map = {}
    for p in pages:
        node_id = p["path"].replace(".md", "")
        page_map[node_id] = p
        nodes.append({
            "id": node_id,
            "label": p["title"],
            "node_type": p["type"],
            "size": 1,
            "community": -1,
            "metadata": {"path": p["path"]},
        })

    # Read full content for each page: extract wikilinks, sources, neighbors
    link_graph: dict[str, set[str]] = defaultdict(set)   # node_id -> out-link targets
    in_links: dict[str, set[str]] = defaultdict(set)      # node_id -> in-link sources
    source_map: dict[str, set[str]] = defaultdict(set)     # source_path -> node_ids using it
    node_sources: dict[str, set[str]] = {}                 # node_id -> set of source paths
    prerequisite_map: dict[str, set[str]] = defaultdict(set)  # node_id -> set of prerequisite node_ids

    for node_id in page_map:
        full_path = wp / page_map[node_id]["path"]
        if not full_path.exists():
            node_sources[node_id] = set()
            continue
        content = full_path.read_text(encoding="utf-8")
        fm, _ = parse_frontmatter(content)

        # Wikilinks
        for match in WIKILINK_RE.finditer(content):
            target = match.group(1).strip()
            if target in page_map and target != node_id:
                link_graph[node_id].add(target)
                in_links[target].add(node_id)

        # Sources
        srcs = set(fm.get("sources", []))
        node_sources[node_id] = srcs
        for src in srcs:
            source_map[src].add(node_id)

        # Prerequisites from frontmatter
        prereqs = fm.get("prerequisites", [])
        for prereq in prereqs:
            # Normalize: remove .md extension to match node_id format
            prereq_id = prereq.replace(".md", "").strip()
            if prereq_id in page_map and prereq_id != node_id:
                prerequisite_map[node_id].add(prereq_id)

    # Neighbor sets and degrees (for Adamic-Adar)
    neighbors: dict[str, set[str]] = {}
    degrees: dict[str, int] = {}
    for node_id in page_map:
        nbrs = link_graph[node_id] | in_links[node_id]
        neighbors[node_id] = nbrs
        degrees[node_id] = len(nbrs)

    # Collect candidate edge pairs: direct links + source overlap + prerequisites
    edge_set: set[tuple[str, str]] = set()
    # Track directed prerequisite relationships: (prerequisite, dependent)
    prereq_directed: set[tuple[str, str]] = set()

    for src_id, targets in link_graph.items():
        for tgt_id in targets:
            edge_set.add((min(src_id, tgt_id), max(src_id, tgt_id)))

    for _src_path, node_set in source_map.items():
        node_list = list(node_set)
        for i in range(len(node_list)):
            for j in range(i + 1, len(node_list)):
                edge_set.add((min(node_list[i], node_list[j]), max(node_list[i], node_list[j])))

    # Prerequisite edges from frontmatter (directed: prereq -> dependent)
    for node_id, prereqs in prerequisite_map.items():
        for prereq_id in prereqs:
            edge_set.add((min(prereq_id, node_id), max(prereq_id, node_id)))
            prereq_directed.add((prereq_id, node_id))

    # Calculate 4-signal relevance for each candidate pair
    edge_list: list[dict] = []
    for a, b in edge_set:
        type_a = page_map[a]["type"]
        type_b = page_map[b]["type"]

        # Signal 1: Direct links (bidirectional count × 3.0)
        forward = 1 if b in link_graph.get(a, set()) else 0
        backward = 1 if a in link_graph.get(b, set()) else 0
        direct_score = (forward + backward) * WEIGHTS["direct_link"]

        # Signal 2: Source overlap (shared source count × 4.0)
        shared_sources = len(node_sources.get(a, set()) & node_sources.get(b, set()))
        source_score = shared_sources * WEIGHTS["source_overlap"]

        # Signal 3: Common neighbors — Adamic-Adar (sum 1/log(degree) × 1.5)
        nbrs_a = neighbors.get(a, set())
        nbrs_b = neighbors.get(b, set())
        adamic_adar = 0.0
        for common in nbrs_a & nbrs_b:
            deg = max(degrees.get(common, 2), 2)
            adamic_adar += 1.0 / math.log(deg)
        neighbor_score = adamic_adar * WEIGHTS["common_neighbor"]

        # Signal 4: Type affinity (affinity matrix value × 1.0)
        affinity = TYPE_AFFINITY.get(type_a, {}).get(type_b, 0.5)
        type_score = affinity * WEIGHTS["type_affinity"]

        total = round(direct_score + source_score + neighbor_score + type_score, 2)

        # Determine edge type and direction
        # For prerequisite edges: source=prerequisite, target=dependent
        edge_type = "related"
        prereq_source = None  # Which node is the prerequisite?

        # Check frontmatter prerequisites (highest priority)
        if (a, b) in prereq_directed:
            edge_type = "prerequisite"
            prereq_source = a
        elif (b, a) in prereq_directed:
            edge_type = "prerequisite"
            prereq_source = b
        else:
            # Infer from wikilink direction + type hierarchy
            # If A links to B, A references B — B is likely a prerequisite of A
            order_a = PREREQ_TYPE_ORDER.get(type_a, 99)
            order_b = PREREQ_TYPE_ORDER.get(type_b, 99)
            if b in link_graph.get(a, set()) and order_b <= order_a:
                # A links to B, B is more foundational → B is prereq of A
                edge_type = "prerequisite"
                prereq_source = b
            elif a in link_graph.get(b, set()) and order_a <= order_b:
                # B links to A, A is more foundational → A is prereq of B
                edge_type = "prerequisite"
                prereq_source = a

        # For prerequisite edges, ensure source=prerequisite, target=dependent
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

    # Community detection
    communities = []
    community_map = {}
    if HAS_NETWORKX and len(nodes) > 2:
        G = nx.Graph()
        for node in nodes:
            G.add_node(node["id"])
        for e in edge_list:
            G.add_edge(e["source"], e["target"], weight=e["weight"])

        try:
            comms = louvain_communities(G, weight="weight", seed=42)
            for i, comm in enumerate(comms):
                members = list(comm)
                for member in members:
                    community_map[member] = i

                # Calculate cohesion
                if len(members) > 1:
                    subgraph = G.subgraph(members)
                    possible = len(members) * (len(members) - 1) / 2
                    actual = subgraph.number_of_edges()
                    cohesion = actual / possible if possible > 0 else 0
                else:
                    cohesion = 0.0

                communities.append({
                    "id": i,
                    "label": f"Cluster {i + 1}",
                    "cohesion": round(cohesion, 3),
                    "member_count": len(members),
                    "top_node": max(members, key=lambda m: G.degree(m)) if members else "",
                })
        except Exception:
            pass

    # Update node communities
    for node in nodes:
        node["community"] = community_map.get(node["id"], -1)

    # Graph insights
    insights = generate_insights(nodes, edge_list, communities, page_map)

    return {
        "nodes": nodes,
        "edges": edge_list,
        "communities": communities,
        "insights": insights,
    }


def generate_insights(nodes: list, edges: list, communities: list,
                      page_map: dict) -> list[dict]:
    """Generate graph insights: isolated nodes, bridges, gaps."""
    insights = []

    # Build adjacency
    adjacency = defaultdict(set)
    for e in edges:
        adjacency[e["source"]].add(e["target"])
        adjacency[e["target"]].add(e["source"])

    # Isolated pages (degree <= 1)
    isolated = [n for n in nodes if len(adjacency.get(n["id"], set())) <= 1]
    if isolated:
        insights.append({
            "insight_type": "knowledge_gap",
            "title": f"{len(isolated)} isolated knowledge points",
            "description": f"The following concepts have few connections: {', '.join(n['label'] for n in isolated[:5])}",
            "node_ids": [n["id"] for n in isolated],
            "score": len(isolated) * 0.5,
        })

    # Low cohesion communities
    for comm in communities:
        if comm["cohesion"] < 0.15 and comm["member_count"] >= 3:
            insights.append({
                "insight_type": "knowledge_gap",
                "title": f"Sparse community: {comm['label']}",
                "description": f"Knowledge cluster with {comm['member_count']} members has low internal cohesion ({comm['cohesion']}). Consider adding more cross-references.",
                "node_ids": [],
                "score": (1.0 - comm["cohesion"]) * 2,
            })

    # Bridge nodes (connecting multiple communities)
    community_map = {}
    for n in nodes:
        if n["community"] >= 0:
            community_map[n["id"]] = n["community"]

    for n in nodes:
        if n["id"] not in community_map:
            continue
        neighbor_communities = set()
        for neighbor in adjacency.get(n["id"], set()):
            if neighbor in community_map:
                neighbor_communities.add(community_map[neighbor])
        if len(neighbor_communities) >= 3:
            insights.append({
                "insight_type": "bridge",
                "title": f"Bridge concept: {n['label']}",
                "description": f"This concept connects {len(neighbor_communities)} different knowledge clusters. It's a critical junction point.",
                "node_ids": [n["id"]],
                "score": len(neighbor_communities) * 1.5,
            })

    # Surprising connections (cross-type edges)
    cross_type_edges = []
    for e in edges:
        src_node = next((n for n in nodes if n["id"] == e["source"]), None)
        tgt_node = next((n for n in nodes if n["id"] == e["target"]), None)
        if src_node and tgt_node and src_node["node_type"] != tgt_node["node_type"]:
            if "formula" in [src_node["node_type"], tgt_node["node_type"]] and \
               "exercise" in [src_node["node_type"], tgt_node["node_type"]]:
                cross_type_edges.append({
                    "src": src_node["label"],
                    "tgt": tgt_node["label"],
                    "types": f"{src_node['node_type']} ↔ {tgt_node['node_type']}",
                })

    if cross_type_edges[:3]:
        for cte in cross_type_edges[:3]:
            insights.append({
                "insight_type": "surprising_connection",
                "title": f"Cross-type link: {cte['src']} ↔ {cte['tgt']}",
                "description": f"Interesting connection between different knowledge types ({cte['types']})",
                "node_ids": [],
                "score": 2.0,
            })

    return insights


def get_node_neighborhood(node_id: str, depth: int = 1, *, project_id: str = "default") -> dict:
    """Get a node and its neighbors up to specified depth."""
    graph = build_graph(project_id=project_id)
    nodes_by_id = {n["id"]: n for n in graph["nodes"]}

    if node_id not in nodes_by_id:
        return {"nodes": [], "edges": []}

    visited = {node_id}
    frontier = {node_id}
    neighborhood_nodes = [nodes_by_id[node_id]]
    neighborhood_edges = []

    for _ in range(depth):
        next_frontier = set()
        for e in graph["edges"]:
            if e["source"] in frontier and e["target"] not in visited:
                next_frontier.add(e["target"])
                neighborhood_edges.append(e)
                if e["target"] in nodes_by_id:
                    neighborhood_nodes.append(nodes_by_id[e["target"]])
            elif e["target"] in frontier and e["source"] not in visited:
                next_frontier.add(e["source"])
                neighborhood_edges.append(e)
                if e["source"] in nodes_by_id:
                    neighborhood_nodes.append(nodes_by_id[e["source"]])
        visited.update(next_frontier)
        frontier = next_frontier

    return {"nodes": neighborhood_nodes, "edges": neighborhood_edges}
