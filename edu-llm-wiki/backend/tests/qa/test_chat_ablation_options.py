"""Tests for chat ablation options used in the EduWiki evaluation protocol."""

import asyncio

from models.chat import ChatOptions
from routes import chat


def test_chat_options_expose_ablation_controls():
    options = ChatOptions()
    assert options.retrieval_mode == "graph"
    assert options.include_learner_state is True


def test_none_retrieval_mode_skips_search_and_graph(tmp_path, monkeypatch):
    (tmp_path / "purpose.md").write_text("Test purpose", encoding="utf-8")
    (tmp_path / "index.md").write_text("Test index", encoding="utf-8")

    monkeypatch.setattr(chat, "wiki_path", lambda project_id: tmp_path)
    monkeypatch.setattr(
        chat,
        "_scope_seed_results",
        lambda scope, *, project_id="default": [{"path": "a.md", "title": "A", "score": 10}],
    )
    monkeypatch.setattr(
        chat,
        "keyword_search",
        lambda query, top_k=10, project_id="default": [{"path": "a.md", "title": "A", "score": 10}],
    )

    import services.vector_store as vector_store

    def fake_vector_search(query, top_k=20, project_id="default"):
        return [{"path": "a.md", "title": "A", "snippet": "A content", "score": 0.9}]

    monkeypatch.setattr(vector_store, "vector_search", fake_vector_search)

    async def fail_graph(*args, **kwargs):
        raise AssertionError("graph retrieval must not run in the none condition")

    monkeypatch.setattr(chat, "collect_graph_evidence", fail_graph)
    monkeypatch.setattr(chat, "_format_learner_profile", lambda project_id, user_id: "Learner profile")

    result = asyncio.run(chat._run_rag_pipeline(
        "What is A?",
        {"page_budget": 20_000, "max_page_size": 5_000, "index_budget": 1_000},
        project_id="default",
        user_id="test-user",
        retrieval_mode="none",
        include_learner_state=False,
    ))

    pages_context, cited, page_list, index, purpose, learner_profile = result
    assert "No relevant wiki pages found" in pages_context
    assert cited == []
    assert "No pages matched" in page_list
    assert "disabled" in learner_profile.lower()


def test_vector_retrieval_mode_uses_search_without_graph(tmp_path, monkeypatch):
    (tmp_path / "purpose.md").write_text("Test purpose", encoding="utf-8")
    (tmp_path / "index.md").write_text("Test index", encoding="utf-8")

    monkeypatch.setattr(chat, "wiki_path", lambda project_id: tmp_path)
    monkeypatch.setattr(
        chat,
        "_scope_seed_results",
        lambda scope, *, project_id="default": [],
    )
    monkeypatch.setattr(
        chat,
        "keyword_search",
        lambda query, top_k=10, project_id="default": [],
    )

    import services.vector_store as vector_store

    def fake_vector_search(query, top_k=20, project_id="default"):
        return [{"path": "a.md", "title": "A", "snippet": "A content", "score": 0.9}]

    monkeypatch.setattr(vector_store, "vector_search", fake_vector_search)
    monkeypatch.setattr(
        chat,
        "read_wiki_page",
        lambda path, project_id="default": {"title": "A", "content": "A full content"},
    )
    monkeypatch.setattr(chat, "_page_body", lambda path, project_id="default": "A full content")

    async def fail_graph(*args, **kwargs):
        raise AssertionError("graph retrieval must not run in the vector condition")

    monkeypatch.setattr(chat, "collect_graph_evidence", fail_graph)
    monkeypatch.setattr(chat, "_format_learner_profile", lambda project_id, user_id: "Learner profile")

    result = asyncio.run(chat._run_rag_pipeline(
        "What is A?",
        {"page_budget": 20_000, "max_page_size": 5_000, "index_budget": 1_000},
        project_id="default",
        user_id="test-user",
        retrieval_mode="vector",
        include_learner_state=True,
    ))

    pages_context, cited, page_list, index, purpose, learner_profile = result
    assert "A full content" in pages_context
    assert len(cited) == 1
    assert cited[0]["path"] == "a.md"
    assert learner_profile == "Learner profile"


def test_chat_options_model_is_passed_to_llm(monkeypatch):
    from models.chat import ChatMessage, ChatRequest

    monkeypatch.setattr(chat, "_require_admin_token", lambda *args, **kwargs: None)

    async def fake_pipeline(*args, **kwargs):
        return ("context", [], "page list", "index", "purpose", "profile")

    captured = {}

    async def fake_chat_complete(*, system_prompt, messages, model=None, **kwargs):
        captured["model"] = model
        return "answer"

    monkeypatch.setattr(chat, "_run_rag_pipeline", fake_pipeline)
    monkeypatch.setattr(chat, "chat_complete", fake_chat_complete)
    monkeypatch.setattr(chat, "_filter_actual_citations", lambda response, cited: ("answer", []))

    request = ChatRequest(
        messages=[ChatMessage(role="user", content="What is A?")],
        options=ChatOptions(model="test-model"),
    )
    result = asyncio.run(chat.chat(request, project_id="default"))

    assert captured["model"] == "test-model"
    assert result.content == "answer"
