import asyncio

from services import search_engine


def test_graph_expand_skips_neighbors_without_pages(monkeypatch):
    """Graph-only nodes must not become unopenable search results."""
    nodes = [
        {"id": "a", "label": "Alpha", "page_path": "alpha.md"},
        {"id": "b", "label": "Beta", "page_path": "beta.md"},
        {"id": "c", "label": "Concept-only", "node_type": "concept"},
    ]
    edges = [
        {"source": "a", "target": "b", "weight": 2.0},
        {"source": "a", "target": "c", "weight": 3.0},
    ]
    exposures = []

    monkeypatch.setattr(search_engine, "get_nodes", lambda project_id: nodes)
    monkeypatch.setattr(search_engine, "get_edges", lambda project_id: edges)
    monkeypatch.setattr(
        search_engine,
        "_page_body",
        lambda path, *, project_id="default": f"content for {path}",
    )
    monkeypatch.setattr(
        search_engine,
        "record_exposure",
        lambda *, project_id, user_id, node_id: exposures.append(node_id),
    )

    result = asyncio.run(search_engine.graph_expand(
        [{"path": "alpha.md", "title": "Alpha", "snippet": "", "score": 10.0}],
        project_id="test-project",
    ))

    assert [item["path"] for item in result] == ["alpha.md", "beta.md"]
    assert exposures == ["b"]
