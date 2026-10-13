"""Import remains usable when optional LLM enrichment is unavailable."""

from __future__ import annotations

import asyncio

from services import extraction, ingest_engine, relation_extraction


def test_extract_chunk_timeout_returns_fallback_signal(monkeypatch):
    async def stalled(*_args, **_kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(extraction, "chat_complete", stalled)
    monkeypatch.setattr(extraction, "LLM_EXTRACTION_TIMEOUT_SECONDS", 0.001)

    result = asyncio.run(
        extraction.extract_chunk("# 材料\n\n内容", source_title="材料.md", page_range="全文")
    )

    assert result == {}


def test_relation_timeout_is_empty_enrichment(monkeypatch):
    async def stalled(*_args, **_kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(relation_extraction, "chat_complete", stalled)
    monkeypatch.setattr(relation_extraction, "LLM_RELATION_TIMEOUT_SECONDS", 0.001)

    result = asyncio.run(
        relation_extraction.extract_relations(
            [{"name": "牛顿第二定律", "type": "Principle"}],
            source_title="材料.md",
        )
    )

    assert result == []


def test_page_generation_timeout_returns_no_llm_pages(monkeypatch):
    async def stalled(*_args, **_kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(ingest_engine, "chat_complete", stalled)
    monkeypatch.setattr(ingest_engine, "LLM_PAGE_GENERATION_TIMEOUT_SECONDS", 0.001)

    result = asyncio.run(
        ingest_engine._generate_core_page_batch(
            {"concepts": [{"name": "概念", "definition": "定义"}]},
            source_title="材料.md",
            purpose="教学",
        )
    )

    assert result == []


def test_first_vector_sync_builds_missing_table(monkeypatch):
    """A first import must create the LanceDB table before incremental writes."""
    from services import ingest_engine, vector_store

    indexed: list[dict] = []

    monkeypatch.setattr(vector_store, "table_exists", lambda project_id="default": False)
    monkeypatch.setattr(
        vector_store,
        "index_pages",
        lambda pages, project_id="default": indexed.extend(pages),
    )
    monkeypatch.setattr(
        vector_store,
        "index_single_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("incremental path used")),
    )
    monkeypatch.setattr(
        ingest_engine,
        "list_wiki_pages",
        lambda project_id="default": [{"path": "concepts/a.md", "title": "A", "type": "concept"}],
    )
    monkeypatch.setattr(
        ingest_engine,
        "read_wiki_page",
        lambda path, project_id="default": {"content": "# A\n\ncontent"},
    )

    ingest_engine._sync_vectors_blocking(
        [{"path": "concepts/a.md", "title": "A", "page_type": "concept"}],
        project_id="demo",
    )

    assert indexed == [{
        "path": "concepts/a.md",
        "title": "A",
        "type": "concept",
        "content": "# A\n\ncontent",
    }]
