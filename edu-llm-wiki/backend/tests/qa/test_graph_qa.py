import asyncio

from services import graph_qa


def test_collect_graph_evidence_expands_until_sufficient(monkeypatch):
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
            "weight": 1.0, "evidence": "another failure mechanism",
        },
    ]

    monkeypatch.setattr(graph_qa, "get_nodes", lambda project_id: nodes)
    monkeypatch.setattr(graph_qa, "get_edges", lambda project_id: edges)
    monkeypatch.setattr(
        graph_qa,
        "read_wiki_page",
        lambda path, project_id: {"title": path, "content": f"Full content for {path}"},
    )
    monkeypatch.setattr(graph_qa, "record_exposure", lambda **kwargs: None)

    calls = []

    async def fake_chat_complete(**kwargs):
        calls.append(kwargs["messages"][0]["content"])
        if len(calls) == 1:
            return '{"sufficient": false, "candidate_ids": ["b"], "missing": ["fatigue mechanism"]}'
        return '{"sufficient": true, "candidate_ids": [], "missing": []}'

    monkeypatch.setattr(graph_qa, "chat_complete", fake_chat_complete)

    result = asyncio.run(graph_qa.collect_graph_evidence(
        "Explain how fatigue causes failure",
        [{"path": "failure.md", "title": "Failure", "score": 10, "title_match": True}],
        {"page_budget": 20_000, "max_page_size": 5_000},
        max_rounds=2,
    ))

    assert result.model_calls == 2
    assert result.rounds == 2
    assert result.sufficient is True
    assert [page["path"] for page in result.pages] == ["failure.md", "fatigue.md"]
    assert result.relations[0]["edge_type"] == "prerequisite"
    assert "Candidate graph frontier" in calls[0]
    assert "fatigue mechanism" in calls[1]
