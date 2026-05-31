"""Knowledge Graph Engine.

Builds a graph from wiki pages:
- Nodes: concepts, formulas, principles, courses, sources
- Edges: wikilinks, source overlap, type affinity
- Community detection: Louvain algorithm
- Graph insights: isolated nodes, bridges, surprising connections
"""

import re
import json
from collections import defaultdict
from pathlib import Path
from config import settings
from storage.wiki_store import wiki_path, list_wiki_pages, parse_frontmatter

try:
    import networkx as nx
    from networkx.algorithms.community import louvain_communities
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False


WIKILINK_RE = re.compile(r'\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]')


def build_graph(*, project_id: str = "default") -> dict:
    """Build the knowledge graph from wiki pages. Returns GraphData-compatible dict."""
    nodes = []
    edges = []
    pages = list_wiki_pages(project_id=project_id)

    # Build node id -> page info mapping
    page_map = {}
    for p in pages:
        node_id = p["path"].replace(".md", "")
        page_map[node_id] = p

        # Determine node type (map page types to graph node types)
        node_type = p["type"]
        nodes.append({
            "id": node_id,
            "label": p["title"],
            "node_type": node_type,
            "size": 1,
            "community": -1,
            "metadata": {"path": p["path"]},
        })

    # Extract wikilinks to build edges
    wp = wiki_path(project_id)
    link_graph = defaultdict(set)
    source_map = defaultdict(set)  # source_path -> set of node_ids

    for node_id, p in page_map.items():
        full_path = wp / p["path"]
        if full_path.exists():
            content = full_path.read_text(encoding="utf-8")
            # Extract wikilinks
            for match in WIKILINK_RE.finditer(content):
                target = match.group(1).strip()
                if target in page_map and target != node_id:
                    link_graph[node_id].add(target)
            # Extract sources
            for src in p.get("sources", []):
                source_map[src].add(node_id)

    # Build edges with weights
    edge_set = set()
    edge_list = []

    # Direct links (weight 3.0)
    for src_id, targets in link_graph.items():
        for tgt_id in targets:
            key = tuple(sorted([src_id, tgt_id]))
            if key not in edge_set:
                edge_set.add(key)
                edge_list.append({
                    "source": src_id,
                    "target": tgt_id,
                    "edge_type": "related",
                    "weight": 3.0,
                })

    # Source overlap (weight 4.0)
    node_ids = list(page_map.keys())
    for i in range(len(node_ids)):
        for j in range(i + 1, len(node_ids)):
            a, b = node_ids[i], node_ids[j]
            key = (min(a, b), max(a, b))
            if key in edge_set:
                continue
            # Check if they share sources
            sources_a = set(page_map.get(a, {}).get("sources", []))
            sources_b = set(page_map.get(b, {}).get("sources", []))
            overlap = sources_a & sources_b
            if overlap:
                edge_set.add(key)
                edge_list.append({
                    "source": a,
                    "target": b,
                    "edge_type": "related",
                    "weight": 4.0,
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
    node_ids = {n["id"] for n in nodes}

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
