"""Vector indexing and search over wiki pages using local embeddings + LanceDB.

Uses sentence-transformers (all-MiniLM-L6-v2) for local embeddings — no API needed.
One-time model download (~80 MB) on first use.
"""

import os
from pathlib import Path

from config import settings

# Lazy-loaded globals
_embedder = None
_db = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        # Kill SOCKS proxy before importing — sentence-transformers uses
        # huggingface_hub + httpx which chokes on socks:// ALL_PROXY
        for key in ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy"):
            os.environ.pop(key, None)

        from sentence_transformers import SentenceTransformer
        model_name = settings.embedding_model or "all-MiniLM-L6-v2"
        _embedder = SentenceTransformer(model_name)
    return _embedder


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a list of texts. Returns list of float vectors."""
    m = _get_embedder()
    result = m.encode(texts, normalize_embeddings=True)
    return result.tolist()


def embed_query(query: str) -> list[float]:
    return embed_texts([query])[0]


def _get_db():
    global _db
    if _db is None:
        import lancedb
        db_path = Path(settings.data_dir) / "vectors"
        db_path.mkdir(parents=True, exist_ok=True)
        _db = lancedb.connect(str(db_path))
    return _db


def _table_name(project_id: str) -> str:
    return f"wiki_{project_id}"


def table_exists(project_id: str = "default") -> bool:
    return _table_name(project_id) in _get_db().table_names()


def index_pages(pages: list[dict], *, project_id: str = "default"):
    """Build or rebuild the vector index for a set of wiki pages.

    Each page dict should have: path, title, type, content
    """
    db = _get_db()
    table_name = _table_name(project_id)
    texts = [p.get("content", "") for p in pages]

    if not texts:
        return

    vectors = embed_texts(texts)

    records = []
    for i, page in enumerate(pages):
        records.append({
            "path": page["path"],
            "title": page.get("title", ""),
            "page_type": page.get("type", page.get("page_type", "")),
            "content": page.get("content", "")[:2000],
            "vector": vectors[i],
        })

    if table_name in db.table_names():
        db.drop_table(table_name)

    db.create_table(table_name, records)
    return len(records)


def index_single_page(page: dict, *, project_id: str = "default"):
    """Insert or update a single page in the vector index."""
    db = _get_db()
    table_name = _table_name(project_id)

    content = page.get("content", "")
    vec = embed_texts([content])[0]

    record = {
        "path": page["path"],
        "title": page.get("title", ""),
        "page_type": page.get("type", page.get("page_type", "")),
        "content": content[:2000],
        "vector": vec,
    }

    t = db.open_table(table_name)
    # Delete existing if present
    try:
        t.delete(f"path = '{page['path']}'")
    except Exception:
        pass
    t.add([record])


def remove_page(path: str, *, project_id: str = "default"):
    """Remove a single page from the vector index."""
    db = _get_db()
    table_name = _table_name(project_id)
    if table_name not in db.table_names():
        return
    t = db.open_table(table_name)
    try:
        t.delete(f"path = '{path}'")
    except Exception:
        pass


def vector_search(query: str, top_k: int = 20, *, project_id: str = "default") -> list[dict]:
    """Semantic search: embed query → cosine similarity in LanceDB."""
    db = _get_db()
    table_name = _table_name(project_id)

    if table_name not in db.table_names():
        return []

    query_vec = embed_query(query)
    t = db.open_table(table_name)
    results = t.search(query_vec).metric("cosine").limit(top_k).to_list()

    out: list[dict] = []
    for r in results:
        # LanceDB returns a cosine distance (lower is better). Expose a
        # higher-is-better similarity to keep the search API score direction
        # consistent with keyword and graph scores.
        distance = float(r.get("_distance", 1.0))
        similarity = max(0.0, min(1.0, 1.0 - distance))
        out.append({
            "path": r["path"],
            "title": r.get("title", ""),
            "snippet": (r.get("content", "") or "")[:200],
            "score": round(similarity, 3),
            "title_match": False,
            "vector_score": round(similarity, 3),
        })
    return out
