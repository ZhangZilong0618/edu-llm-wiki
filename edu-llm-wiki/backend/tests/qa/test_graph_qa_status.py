import asyncio

from services import graph_qa


def test_collect_graph_evidence_emits_status(monkeypatch):
    """Status callback must fire at every interesting transition."""
    nodes = [
        {"id": "a", "label": "Failure", "node_type": "concept", "page_path": "failure.md"},
        {"id": "b", "label": "Fatigue", "node_type": "concept", "page_path": "fatigue.md"},
        {"id": "c", "label": "Corrosion", "node_type": "concept", "page_path": "corrosion.md"},
    ]
    edges = [
        {
            "source": "a", "target": "b", "edge_type": "prerequisite",
            "weight": 2.0, "evidence": "fatigue is a failure mechanism",
        },
        {
            "source": "a", "target": "c", "edge_type": "related",
            "weight": 1.5, "evidence": "another failure mechanism",
        },
    ]

    monkeypatch.setattr(graph_qa, "get_nodes", lambda project_id: nodes)
    monkeypatch.setattr(graph_qa, "get_edges", lambda project_id: edges)
    monkeypatch.setattr(
        graph_qa,
        "read_wiki_page",
        lambda path, project_id: {"title": path, "content": f"Full content for {path}"},
    )

    calls = []

    async def fake_chat_complete(**kwargs):
        calls.append(kwargs["messages"][0]["content"])
        # Round 1: not enough; pick fatigue. Round 2: sufficient.
        if len(calls) == 1:
            return '{"sufficient": false, "candidate_ids": ["b"], "missing": ["fatigue mechanism"]}'
        return '{"sufficient": true, "candidate_ids": [], "missing": []}'

    monkeypatch.setattr(graph_qa, "chat_complete", fake_chat_complete)

    statuses = []

    async def on_status(text: str) -> None:
        statuses.append(text)

    result = asyncio.run(graph_qa.collect_graph_evidence(
        "Explain fatigue",
        [{"path": "failure.md", "title": "Failure", "score": 10, "title_match": True}],
        {"page_budget": 20_000, "max_page_size": 5_000},
        max_rounds=2,
        on_status=on_status,
    ))

    # Pre-loop announcement, two round banners, "read N pages" line for round 1,
    # and final summary line.
    assert any("正在沿知识图谱" in s for s in statuses), statuses
    assert any("第 1/2 轮" in s for s in statuses), statuses
    assert any("第 2/2 轮" in s for s in statuses), statuses
    assert any("已读取" in s for s in statuses), statuses
    assert any("图谱检索完成" in s for s in statuses), statuses
    assert result.model_calls == 2
    assert result.rounds == 2
    assert result.sufficient is True


def test_status_callback_is_optional(monkeypatch):
    """No on_status supplied => function still works (no callback errors)."""
    nodes = [{"id": "a", "label": "Failure", "node_type": "concept", "page_path": "failure.md"}]
    monkeypatch.setattr(graph_qa, "get_nodes", lambda project_id: nodes)
    monkeypatch.setattr(graph_qa, "get_edges", lambda project_id: [])
    monkeypatch.setattr(
        graph_qa,
        "read_wiki_page",
        lambda path, project_id: {"title": path, "content": "x" * 50},
    )

    async def fake_chat_complete(**kwargs):
        return '{"sufficient": true, "candidate_ids": [], "missing": []}'
    monkeypatch.setattr(graph_qa, "chat_complete", fake_chat_complete)

    result = asyncio.run(graph_qa.collect_graph_evidence(
        "test",
        [{"path": "failure.md", "title": "Failure", "score": 1, "title_match": True}],
        {"page_budget": 20_000, "max_page_size": 5_000},
        max_rounds=2,
    ))
    assert result.pages  # seed was added


def test_status_callback_failure_does_not_break_pipeline(monkeypatch):
    """A buggy status callback must not abort retrieval."""
    nodes = [{"id": "a", "label": "Failure", "node_type": "concept", "page_path": "failure.md"}]
    monkeypatch.setattr(graph_qa, "get_nodes", lambda project_id: nodes)
    monkeypatch.setattr(graph_qa, "get_edges", lambda project_id: [])
    monkeypatch.setattr(
        graph_qa,
        "read_wiki_page",
        lambda path, project_id: {"title": path, "content": "y" * 50},
    )

    async def fake_chat_complete(**kwargs):
        return '{"sufficient": true, "candidate_ids": [], "missing": []}'
    monkeypatch.setattr(graph_qa, "chat_complete", fake_chat_complete)

    async def bad_status(text: str) -> None:
        raise RuntimeError("simulated UI failure")

    result = asyncio.run(graph_qa.collect_graph_evidence(
        "test",
        [{"path": "failure.md", "title": "Failure", "score": 1, "title_match": True}],
        {"page_budget": 20_000, "max_page_size": 5_000},
        max_rounds=2,
        on_status=bad_status,
    ))
    assert result.pages


def test_collect_graph_evidence_stops_when_frontier_exhausted(monkeypatch):
    """After expanding the only neighbor, no frontier remains; loop should exit cleanly."""
    nodes = [
        {"id": "a", "label": "Failure", "node_type": "concept", "page_path": "failure.md"},
        {"id": "b", "label": "Fatigue", "node_type": "concept", "page_path": "fatigue.md"},
    ]
    edges = [
        {
            "source": "a", "target": "b", "edge_type": "prerequisite",
            "weight": 2.0, "evidence": "fatigue is a failure mechanism",
        },
    ]

    monkeypatch.setattr(graph_qa, "get_nodes", lambda project_id: nodes)
    monkeypatch.setattr(graph_qa, "get_edges", lambda project_id: edges)
    monkeypatch.setattr(
        graph_qa,
        "read_wiki_page",
        lambda path, project_id: {"title": path, "content": f"content {path}"},
    )

    async def fake_chat_complete(**kwargs):
        # Always ask for more — but after round 1 there is no frontier.
        return '{"sufficient": false, "candidate_ids": ["b"], "missing": ["more"]}'

    monkeypatch.setattr(graph_qa, "chat_complete", fake_chat_complete)

    statuses = []

    async def on_status(text: str) -> None:
        statuses.append(text)

    result = asyncio.run(graph_qa.collect_graph_evidence(
        "Explain fatigue",
        [{"path": "failure.md", "title": "Failure", "score": 10, "title_match": True}],
        {"page_budget": 20_000, "max_page_size": 5_000},
        max_rounds=3,
        on_status=on_status,
    ))

    # Only one round of model calls — round 2 sees an empty frontier and exits.
    assert result.model_calls == 1
    assert any("没有更多相邻页面" in s for s in statuses), statuses


def test_collect_graph_evidence_falls_back_when_model_fails(monkeypatch):
    """If the controller fails on every call, retrieval still adds the top-weighted neighbour."""
    nodes = [
        {"id": "a", "label": "Failure", "node_type": "concept", "page_path": "failure.md"},
        {"id": "b", "label": "Fatigue", "node_type": "concept", "page_path": "fatigue.md"},
    ]
    edges = [
        {
            "source": "a", "target": "b", "edge_type": "prerequisite",
            "weight": 2.0, "evidence": "fatigue is a failure mechanism",
        },
    ]

    monkeypatch.setattr(graph_qa, "get_nodes", lambda project_id: nodes)
    monkeypatch.setattr(graph_qa, "get_edges", lambda project_id: edges)
    monkeypatch.setattr(
        graph_qa,
        "read_wiki_page",
        lambda path, project_id: {"title": path, "content": f"content {path}"},
    )

    async def fake_chat_complete(**kwargs):
        raise RuntimeError("controller unavailable")

    monkeypatch.setattr(graph_qa, "chat_complete", fake_chat_complete)

    result = asyncio.run(graph_qa.collect_graph_evidence(
        "Explain fatigue",
        [{"path": "failure.md", "title": "Failure", "score": 10, "title_match": True}],
        {"page_budget": 20_000, "max_page_size": 5_000},
        max_rounds=2,
    ))

    # The fallback path picks the top-weighted neighbour even when the
    # controller is unreachable.
    assert any(p["path"] == "fatigue.md" for p in result.pages)


def test_collect_graph_evidence_respects_page_budget(monkeypatch):
    """Once the page budget is exhausted, no more pages should be added."""
    nodes = [
        {"id": "a", "label": "Failure", "node_type": "concept", "page_path": "failure.md"},
        {"id": "b", "label": "Fatigue", "node_type": "concept", "page_path": "fatigue.md"},
    ]
    edges = [
        {
            "source": "a", "target": "b", "edge_type": "prerequisite",
            "weight": 2.0, "evidence": "fatigue is a failure mechanism",
        },
    ]

    monkeypatch.setattr(graph_qa, "get_nodes", lambda project_id: nodes)
    monkeypatch.setattr(graph_qa, "get_edges", lambda project_id: edges)

    def fake_read_wiki_page(path, project_id):
        # Each page is huge so the second read should fail the budget check.
        return {"title": path, "content": "x" * 4_500}

    monkeypatch.setattr(graph_qa, "read_wiki_page", fake_read_wiki_page)

    async def fake_chat_complete(**kwargs):
        return '{"sufficient": false, "candidate_ids": ["b"], "missing": ["more"]}'

    monkeypatch.setattr(graph_qa, "chat_complete", fake_chat_complete)

    result = asyncio.run(graph_qa.collect_graph_evidence(
        "Explain fatigue",
        [{"path": "failure.md", "title": "Failure", "score": 10, "title_match": True}],
        {"page_budget": 5_000, "max_page_size": 4_000},
        max_rounds=2,
    ))

    # Only the seed fits; the neighbour exceeds the budget.
    assert [p["path"] for p in result.pages] == ["failure.md"]
