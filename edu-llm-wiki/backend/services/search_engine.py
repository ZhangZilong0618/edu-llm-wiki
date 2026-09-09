"""Multi-phase search engine.

Phase 1: Tokenized keyword search (CJK bigram + English)
Phase 1.5: Vector semantic search (optional, LanceDB)
Phase 2: Graph expansion (1-2 hop)
"""

import asyncio
import re
from collections import defaultdict
from functools import lru_cache

from config import settings
from services.graph_store import get_edges, get_nodes, make_node_id, record_exposure
from storage.wiki_store import list_wiki_pages, parse_frontmatter, wiki_path

# Stop words for Chinese and English
STOP_WORDS = {
    "的", "是", "了", "什么", "在", "有", "和", "与", "对", "从", "不", "也", "就", "都",
    "the", "is", "a", "an", "what", "how", "are", "was", "were",
    "do", "does", "did", "be", "been", "being", "have", "has", "had",
    "it", "its", "in", "on", "at", "to", "for", "of", "with", "by",
    "this", "that", "these", "those", "can", "will", "would", "could",
}

WIKILINK_RE = re.compile(r'\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]')


@lru_cache(maxsize=512)
def _cached_page_body(
    path: str,
    mtime_ns: int,
    size: int,
    project_id: str,
) -> str:
    """Cache a wiki page body by its file signature.

    The key includes ``mtime`` and size, so normal edits still invalidate the
    entry without a global cache reset.
    """
    full_path = wiki_path(project_id) / path
    raw = full_path.read_text(encoding="utf-8")
    _, body = parse_frontmatter(raw)
    return body


def _page_body(path: str, *, project_id: str = "default") -> str:
    """Return a page body, using the signature-aware cache when possible."""
    full_path = wiki_path(project_id) / path
    try:
        stat = full_path.stat()
    except OSError:
        return ""
    return _cached_page_body(path, stat.st_mtime_ns, stat.st_size, project_id)


def tokenize_query(query: str) -> list[str]:
    """Tokenize query with CJK-aware bigram splitting."""
    raw_tokens = query.lower().split()
    # Also split on Chinese punctuation
    raw_tokens = re.split(r'[\s,，。！？、；：""''（）()\\-_/\\·~～…]+', query.lower())
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

    pages = list_wiki_pages(project_id=project_id)
    page_by_path = {p["path"]: p for p in pages}
    for page in pages:
        path = page["path"]
        try:
            content = _page_body(path, project_id=project_id)
        except Exception:
            content = ""

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

        # Generate snippet. Use ``get`` so zero-score pages are not inserted
        # into the defaultdict merely by being inspected.
        if scores.get(path, 0.0) > 0:
            snippets[path] = _generate_snippet(content, tokens)

    # Sort by score
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    results = []
    for path, score in ranked[:top_k]:
        page = page_by_path.get(path)
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


async def graph_expand(
    results: list[dict],
    depth: int = 1,
    *,
    project_id: str = "default",
    user_id: str = "default",
) -> list[dict]:
    """Phase 2: Expand search results using graph edge weights (4-signal relevance).

    Only expands to neighbors with edge weight >= RELEVANCE_THRESHOLD,
    matching the old Tauri system's behavior.
    """
    RELEVANCE_THRESHOLD = 0.5

    nodes = get_nodes(project_id)
    if not nodes:
        from services.graph_engine import build_graph
        built = build_graph(project_id=project_id)
        nodes = built["nodes"]
    nodes_by_id = {n["id"]: n for n in nodes}
    path_to_node = {
        n.get("page_path") or n.get("metadata", {}).get("path"): n["id"]
        for n in nodes
        if n.get("page_path") or n.get("metadata", {}).get("path")
    }

    # Build weighted adjacency: node_id -> set of (neighbor_id, weight)
    adjacency: dict[str, set[tuple[str, float]]] = defaultdict(set)
    for e in get_edges(project_id):
        adjacency[e["source"]].add((e["target"], e["weight"]))
        adjacency[e["target"]].add((e["source"], e["weight"]))

    seen_paths = {r["path"] for r in results}
    new_results = list(results)

    for r in results[:10]:  # expand from top 10 results
        node_id = path_to_node.get(r["path"]) or make_node_id(project_id, r["path"])
        # Collect neighbors with relevance above threshold
        candidates: list[tuple[str, str, float]] = []
        for neighbor, weight in adjacency.get(node_id, set()):
            if weight < RELEVANCE_THRESHOLD:
                continue
            neighbor_meta = nodes_by_id.get(neighbor, {})
            neighbor_path = (
                neighbor_meta.get("page_path")
                or neighbor_meta.get("metadata", {}).get("path")
                or f"{neighbor}.md"
            )
            if neighbor_path not in seen_paths and neighbor in nodes_by_id:
                candidates.append((neighbor, neighbor_path, weight))
        # Sort by edge weight descending, take top 3 (matching old system: getRelatedNodes limit 3)
        candidates.sort(key=lambda x: -x[2])
        for neighbor, neighbor_path, weight in candidates[:3]:
            seen_paths.add(neighbor_path)
            node = nodes_by_id[neighbor]
            try:
                content = _page_body(neighbor_path, project_id=project_id)
            except Exception:
                content = ""
            # Score combines original score + edge weight (normalized)
            new_results.append({
                "path": neighbor_path,
                "title": node.get("label") or node.get("title") or neighbor,
                "snippet": content[:200],
                "score": round(r["score"] * 0.5 + weight, 2),
                "title_match": False,
                "vector_score": None,
            })

    # Record graph-expanded impressions. The caller decides whether a search
    # result is only an impression or an actual read; expanded hits are useful
    # evidence that the learner was shown adjacent prerequisite material.
    seen: set[str] = set()
    original_paths = {r["path"] for r in results}
    for r in new_results:
        if r["path"] in original_paths:
            continue
        nid = path_to_node.get(r["path"]) or make_node_id(project_id, r["path"])
        if nid in seen:
            continue
        seen.add(nid)
        try:
            record_exposure(project_id=project_id, user_id=user_id, node_id=nid)
        except Exception:
            pass

    return sorted(new_results, key=lambda x: -x["score"])


async def search(
    query: str,
    include_vector: bool = False,
    top_k: int = 20,
    *,
    project_id: str = "default",
    user_id: str = "default",
) -> dict:
    """Full search pipeline: keyword + optional vector + graph expansion."""
    # Phase 1: Keyword search
    results = await asyncio.to_thread(
        keyword_search, query, top_k, project_id=project_id
    )

    # Phase 1.5: Vector search (if enabled)
    vector_hits = 0
    if include_vector and settings.embedding_enabled:
        try:
            vector_results = await _vector_search(query, top_k, project_id=project_id)
            vector_hits = len(vector_results)

            # Merge: boost existing, add new
            result_map = {r["path"]: r for r in results}
            for vr in vector_results:
                similarity = max(0.0, min(1.0, float(vr.get("score", 0.0))))
                vr["score"] = round(similarity * 5.0, 3)
                vr["vector_score"] = round(similarity, 3)
                if vr["path"] in result_map:
                    result_map[vr["path"]]["score"] += vr["score"]
                    result_map[vr["path"]]["vector_score"] = vr["vector_score"]
                else:
                    results.append(vr)
            results = sorted(results, key=lambda x: -x["score"])
        except Exception:
            pass

    # Phase 2: Graph expansion (1-hop from top results)
    try:
        results = await graph_expand(
            results, depth=1, project_id=project_id, user_id=user_id
        )
    except Exception:
        pass

    mode = "hybrid" if vector_hits > 0 else "keyword"
    return {
        "mode": mode,
        "results": results[:top_k],
        "token_hits": len(results),
        "vector_hits": vector_hits,
    }


async def _vector_search(query: str, top_k: int = 20, *, project_id: str = "default") -> list[dict]:
    """Vector semantic search using local embeddings + LanceDB."""
    try:
        from services.vector_store import vector_search
        return await asyncio.to_thread(
            vector_search, query, top_k=top_k, project_id=project_id
        )
    except Exception:
        return []
