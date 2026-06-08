"""Multi-phase search engine.

Phase 1: Tokenized keyword search (CJK bigram + English)
Phase 1.5: Vector semantic search (optional, LanceDB)
Phase 2: Graph expansion (1-2 hop)
"""

import re
import math
from collections import defaultdict
from pathlib import Path
from config import settings
from storage.wiki_store import wiki_path, sources_path, list_wiki_pages, read_wiki_page


# Stop words for Chinese and English
STOP_WORDS = {
    "的", "是", "了", "什么", "在", "有", "和", "与", "对", "从", "不", "也", "就", "都",
    "the", "is", "a", "an", "what", "how", "are", "was", "were",
    "do", "does", "did", "be", "been", "being", "have", "has", "had",
    "it", "its", "in", "on", "at", "to", "for", "of", "with", "by",
    "this", "that", "these", "those", "can", "will", "would", "could",
}

WIKILINK_RE = re.compile(r'\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]')


def tokenize_query(query: str) -> list[str]:
    """Tokenize query with CJK-aware bigram splitting."""
    raw_tokens = query.lower().split()
    # Also split on Chinese punctuation
    raw_tokens = re.split(r'[\s,，。！？、；：""''（）()\-_/\\·~～…]+', query.lower())
    raw_tokens = [t for t in raw_tokens if len(t) > 1]
    raw_tokens = [t for t in raw_tokens if t not in STOP_WORDS]

    tokens = []
    for token in raw_tokens:
        has_cjk = bool(re.search(r'[一-鿿㐀-䶿]', token))
        if has_cjk and len(token) > 2:
            chars = list(token)
            for i in range(len(chars) - 1):
                tokens.append(chars[i] + chars[i + 1])
            for ch in chars:
                if ch not in STOP_WORDS:
                    tokens.append(ch)
            tokens.append(token)
        else:
            tokens.append(token)

    return list(dict.fromkeys(tokens))  # unique, order preserving


def keyword_search(query: str, top_k: int = 20, *, project_id: str = "default") -> list[dict]:
    """Phase 1: Keyword-based search over wiki pages."""
    tokens = tokenize_query(query)
    if not tokens:
        return []

    scores = defaultdict(float)
    title_matches = set()
    snippets = {}

    for page in list_wiki_pages(project_id=project_id):
        path = page["path"]
        content = ""
        try:
            page_data = read_wiki_page(path, project_id=project_id)
            if page_data:
                content = page_data.get("content", "")
        except Exception:
            pass

        title = page.get("title", "")
        title_lower = title.lower()

        # Score title matches
        for token in tokens:
            if token.lower() in title_lower:
                scores[path] += 10.0
                title_matches.add(path)

        # Score content matches
        content_lower = content.lower()
        for token in tokens:
            count = content_lower.count(token.lower())
            if count > 0:
                scores[path] += min(count, 5) * 1.0  # cap per-token contribution

        # Generate snippet
        if scores[path] > 0:
            snippets[path] = _generate_snippet(content, tokens)

    # Sort by score
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    results = []
    for path, score in ranked[:top_k]:
        page = next((p for p in list_wiki_pages(project_id=project_id) if p["path"] == path), None)
        if page:
            results.append({
                "path": path,
                "title": page["title"],
                "snippet": snippets.get(path, ""),
                "score": round(score, 2),
                "title_match": path in title_matches,
                "vector_score": None,
            })

    return results


def _generate_snippet(content: str, tokens: list[str]) -> str:
    """Generate a context snippet around first token match."""
    if not content or not tokens:
        return content[:200] if content else ""

    content_lower = content.lower()
    best_pos = len(content)
    for token in tokens:
        pos = content_lower.find(token.lower())
        if 0 <= pos < best_pos:
            best_pos = pos

    if best_pos >= len(content):
        return content[:200]

    start = max(0, best_pos - 80)
    end = min(len(content), best_pos + 120)
    snippet = content[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(content):
        snippet = snippet + "..."

    return snippet


async def graph_expand(results: list[dict], depth: int = 1, *, project_id: str = "default") -> list[dict]:
    """Phase 2: Expand search results using graph edge weights (4-signal relevance).

    Only expands to neighbors with edge weight >= RELEVANCE_THRESHOLD,
    matching the old Tauri system's behavior.
    """
    from services.graph_engine import build_graph

    RELEVANCE_THRESHOLD = 2.0

    graph = build_graph(project_id=project_id)
    nodes_by_id = {n["id"]: n for n in graph["nodes"]}

    # Build weighted adjacency: node_id -> set of (neighbor_id, weight)
    adjacency: dict[str, set[tuple[str, float]]] = defaultdict(set)
    for e in graph["edges"]:
        adjacency[e["source"]].add((e["target"], e["weight"]))
        adjacency[e["target"]].add((e["source"], e["weight"]))

    seen_paths = {r["path"] for r in results}
    new_results = list(results)

    for r in results[:10]:  # expand from top 10 results
        node_id = r["path"].replace(".md", "")
        # Collect neighbors with relevance above threshold
        candidates: list[tuple[str, str, float]] = []
        for neighbor, weight in adjacency.get(node_id, set()):
            if weight < RELEVANCE_THRESHOLD:
                continue
            neighbor_path = neighbor + ".md"
            if neighbor_path not in seen_paths and neighbor in nodes_by_id:
                candidates.append((neighbor, neighbor_path, weight))
        # Sort by edge weight descending, take top 3 (matching old system: getRelatedNodes limit 3)
        candidates.sort(key=lambda x: -x[2])
        for neighbor, neighbor_path, weight in candidates[:3]:
            seen_paths.add(neighbor_path)
            node = nodes_by_id[neighbor]
            page = read_wiki_page(neighbor_path, project_id=project_id)
            content = page.get("content", "") if page else ""
            # Score combines original score + edge weight (normalized)
            new_results.append({
                "path": neighbor_path,
                "title": node["label"],
                "snippet": content[:200],
                "score": round(r["score"] * 0.5 + weight, 2),
                "title_match": False,
                "vector_score": None,
            })

    return sorted(new_results, key=lambda x: -x["score"])


async def search(query: str, include_vector: bool = False, top_k: int = 20, *, project_id: str = "default") -> dict:
    """Full search pipeline: keyword + optional vector + graph expansion."""
    # Phase 1: Keyword search
    results = keyword_search(query, top_k, project_id=project_id)

    # Phase 1.5: Vector search (if enabled)
    vector_hits = 0
    if include_vector and settings.embedding_enabled:
        try:
            vector_results = await _vector_search(query, top_k)
            vector_hits = len(vector_results)

            # Merge: boost existing, add new
            result_map = {r["path"]: r for r in results}
            for vr in vector_results:
                if vr["path"] in result_map:
                    result_map[vr["path"]]["score"] += 2.0
                    result_map[vr["path"]]["vector_score"] = vr["score"]
                else:
                    results.append(vr)
            results = sorted(results, key=lambda x: -x["score"])
        except Exception:
            pass

    # Phase 2: Graph expansion (1-hop from top results)
    try:
        results = await graph_expand(results, depth=1, project_id=project_id)
    except Exception:
        pass

    mode = "hybrid" if vector_hits > 0 else "keyword"
    return {
        "mode": mode,
        "results": results[:top_k],
        "token_hits": len(results),
        "vector_hits": vector_hits,
    }


async def _vector_search(query: str, top_k: int = 20) -> list[dict]:
    """Vector semantic search using embeddings."""
    try:
        import lancedb
        from openai import AsyncOpenAI

        # Get embedding
        client = AsyncOpenAI(
            api_key=settings.embedding_api_key or "ollama",
            base_url=settings.embedding_endpoint or None,
        )
        resp = await client.embeddings.create(
            model=settings.embedding_model,
            input=[query],
        )
        query_vec = resp.data[0].embedding

        # Connect to LanceDB
        db_path = Path(settings.data_dir) / "vectors"
        db = lancedb.connect(str(db_path))

        if "wiki_pages" not in db.table_names():
            return []

        table = db.open_table("wiki_pages")
        results = table.search(query_vec).metric("cosine").limit(top_k).to_list()

        return [{
            "path": r["path"],
            "title": r.get("title", ""),
            "snippet": r.get("content", "")[:200],
            "score": round(1.0 - r.get("_distance", 0), 3),
            "title_match": False,
            "vector_score": round(1.0 - r.get("_distance", 0), 3),
        } for r in results]
    except ImportError:
        return []
