"""Tests for the MCP tool server and the ReAct agent loop."""

import asyncio

import services.mcp_tools as mcp_tools
import services.react_agent as react_agent
from services.react_agent import ReactAgentError, run_react_agent


def test_evidence_registry_assigns_stable_numbers():
    registry = mcp_tools.EvidenceRegistry(page_budget=1000)
    first = registry.add("a.md", "A", "content of a")
    second = registry.add("b.md", "B", "content of b")
    again = registry.add("a.md", "A", "content of a")

    assert first["number"] == 1
    assert second["number"] == 2
    assert again["number"] == 1
    assert [page["path"] for page in registry.pages] == ["a.md", "b.md"]
    assert registry.used_chars == 0  # budget accounting lives in read_page
    assert registry.citation_list() == "[1] A, [2] B"


def _fake_wiki(monkeypatch, pages: dict[str, dict]):
    monkeypatch.setattr(
        mcp_tools,
        "read_wiki_page",
        lambda path, project_id="default": pages.get(path),
    )
    import services.search_engine as search_engine
    import services.vector_store as vector_store

    monkeypatch.setattr(
        vector_store,
        "vector_search",
        lambda query, top_k=20, project_id="default": [],
    )
    monkeypatch.setattr(
        search_engine,
        "keyword_search",
        lambda query, top_k=10, project_id="default": [],
    )
    import services.search_engine as se

    monkeypatch.setattr(se, "list_wiki_pages", lambda page_type=None, project_id="default": [])
    # _visible_summaries imports list_wiki_pages lazily from storage.
    import storage.wiki_store as wiki_store

    monkeypatch.setattr(
        wiki_store,
        "list_wiki_pages",
        lambda page_type=None, project_id="default": [
            {"path": path, "title": page.get("title"), "type": page.get("page_type", "concept")}
            for path, page in pages.items()
        ],
    )


def test_react_agent_reads_page_over_mcp_and_cites_it(monkeypatch):
    _fake_wiki(monkeypatch, {
        "chem/redox.md": {"title": "氧化还原反应", "content": "氧化还原反应的本质是电子转移。"},
    })

    captured_convo = []
    script = [
        {
            "content": "先读取该页面。",
            "tool_calls": [{"id": "call_1", "name": "read_page", "arguments": {"path": "chem/redox.md"}}],
            "stop_reason": "tool_calls",
        },
        {
            "content": "氧化还原反应的本质是电子转移 [1]。",
            "tool_calls": [],
            "stop_reason": "stop",
        },
    ]
    turns = iter(script)

    async def fake_llm(system_prompt, messages, tools, **kwargs):
        captured_convo.append([dict(message) for message in messages])
        tool_names = {tool["name"] for tool in tools}
        assert "read_page" in tool_names
        assert "search_wiki" in tool_names
        assert "graph_neighbors" in tool_names
        assert "learner_state" in tool_names
        return next(turns)

    monkeypatch.setattr(react_agent, "chat_complete_tools", fake_llm)

    statuses: list[str] = []

    async def on_status(text):
        statuses.append(text)

    result = asyncio.run(run_react_agent(
        "什么是氧化还原反应？",
        [{"role": "user", "content": "什么是氧化还原反应？"}],
        project_id="default",
        on_status=on_status,
    ))

    assert result.answer == "氧化还原反应的本质是电子转移 [1]。"
    assert result.steps == 2
    assert result.tool_calls == 1
    assert result.evidence.pages[0]["path"] == "chem/redox.md"
    assert result.evidence.pages[0]["number"] == 1

    # The second turn must see the MCP observation as a tool message carrying
    # the page's citation number — the core ReAct Observation step.
    second_turn = captured_convo[1]
    assert second_turn[-1]["role"] == "tool"
    assert second_turn[-1]["tool_call_id"] == "call_1"
    assert second_turn[-1]["content"].startswith("[1] 氧化还原反应 (chem/redox.md)")
    assert "电子转移" in second_turn[-1]["content"]

    # The assistant turn in between carries the tool call request.
    assert second_turn[-2]["role"] == "assistant"
    assert second_turn[-2]["tool_calls"][0]["name"] == "read_page"

    assert any("已读取 [1] 氧化还原反应" in text for text in statuses)


def test_react_agent_error_propagates_for_fallback(monkeypatch):
    _fake_wiki(monkeypatch, {})

    async def failing_llm(*args, **kwargs):
        raise RuntimeError("provider has no tool support")

    monkeypatch.setattr(react_agent, "chat_complete_tools", failing_llm)

    try:
        asyncio.run(run_react_agent(
            "question",
            [{"role": "user", "content": "question"}],
            project_id="default",
        ))
    except ReactAgentError as exc:
        assert "tool-calling turn failed" in str(exc)
    else:
        raise AssertionError("expected ReactAgentError")


def test_react_agent_forces_final_answer_after_step_budget(monkeypatch):
    _fake_wiki(monkeypatch, {
        "a.md": {"title": "A", "content": "A 的内容。"},
    })

    looping = {
        "content": "继续收集。",
        "tool_calls": [{"id": "call_loop", "name": "list_wiki_pages", "arguments": {}}],
        "stop_reason": "tool_calls",
    }
    # Only request tools: every turn re-issues a harmless tool call so the
    # loop burns its step budget and must take the forced-answer path.
    calls = {"tools": 0, "final": 0}

    async def fake_llm(system_prompt, messages, tools, **kwargs):
        calls["tools"] += 1
        return dict(looping)

    async def fake_final(system_prompt, messages, model=None, **kwargs):
        calls["final"] += 1
        assert "Evidence Read" in system_prompt or "no pages were read" in system_prompt
        return "预算内作答。"

    monkeypatch.setattr(react_agent, "chat_complete_tools", fake_llm)
    monkeypatch.setattr(react_agent, "chat_complete", fake_final)

    result = asyncio.run(run_react_agent(
        "question",
        [{"role": "user", "content": "question"}],
        project_id="default",
        max_steps=2,
    ))

    assert result.answer == "预算内作答。"
    assert calls["tools"] == 2
    assert calls["final"] == 1


def test_chat_endpoint_falls_back_to_legacy_pipeline(monkeypatch):
    from models.chat import ChatMessage, ChatOptions, ChatRequest
    from routes import chat

    monkeypatch.setattr(chat, "_require_admin_token", lambda *args, **kwargs: None)

    async def failing_agent(*args, **kwargs):
        raise ReactAgentError("no tool support")

    async def fake_pipeline(*args, **kwargs):
        return ("pages context", [], "page list", "index", "purpose", "profile")

    async def fake_chat_complete(*, system_prompt, messages, model=None, **kwargs):
        return "legacy answer"

    monkeypatch.setattr(chat, "run_react_agent", failing_agent)
    monkeypatch.setattr(chat, "_run_rag_pipeline", fake_pipeline)
    monkeypatch.setattr(chat, "chat_complete", fake_chat_complete)
    monkeypatch.setattr(chat, "_filter_actual_citations", lambda response, cited: ("legacy answer", []))

    # Default options request the ReAct agent; the failure must be swallowed
    # and answered by the legacy graph pipeline instead of a 500.
    request = ChatRequest(
        messages=[ChatMessage(role="user", content="What is A?")],
        options=ChatOptions(),
    )
    result = asyncio.run(chat.chat(request, project_id="default"))

    assert result.content == "legacy answer"
    assert result.cited_pages == []


def test_llm_message_conversion_for_anthropic_and_openai():
    from services.llm_client import (
        _anthropic_messages,
        _anthropic_tools,
        _openai_tool_message,
        _openai_tools,
    )

    mcp_tool = {
        "name": "read_page",
        "description": "Read a page.",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    }

    assert _anthropic_tools([mcp_tool])[0]["input_schema"] == mcp_tool["input_schema"]
    assert _openai_tools([mcp_tool])[0]["function"]["parameters"] == mcp_tool["input_schema"]

    messages = [
        {"role": "user", "content": "问题"},
        {"role": "assistant", "content": "想法", "tool_calls": [
            {"id": "call_1", "name": "read_page", "arguments": {"path": "a.md"}},
            {"id": "call_2", "name": "read_page", "arguments": {"path": "b.md"}},
        ]},
        {"role": "tool", "tool_call_id": "call_1", "content": "观察一"},
        {"role": "tool", "tool_call_id": "call_2", "content": "观察二"},
    ]

    # OpenAI: arguments serialise back to JSON strings.
    serialised = _openai_tool_message(messages[1])
    assert serialised["tool_calls"][0]["function"]["arguments"] == '{"path": "a.md"}'
    assert _openai_tool_message(messages[0]) == messages[0]

    # Anthropic: consecutive tool results merge into one user turn.
    converted = _anthropic_messages(messages)
    assert converted[1]["content"][0] == {"type": "text", "text": "想法"}
    assert converted[1]["content"][1]["type"] == "tool_use"
    assert converted[2]["role"] == "user"
    assert [block["content"] for block in converted[2]["content"]] == ["观察一", "观察二"]
