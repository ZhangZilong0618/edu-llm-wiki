from fastapi.testclient import TestClient

from config import settings
from storage.wiki_store import ensure_dirs, write_wiki_page


def test_learner_snapshots_are_hidden_from_wiki_and_stale_vector_search(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    monkeypatch.setattr(settings, "embedding_enabled", True)
    ensure_dirs(project_id="p")
    path = "learning/learners/u_private-token.md"
    write_wiki_page(
        path,
        "学习者活动档案",
        "learner_profile",
        "秘密学习主题和掌握度",
        project_id="p",
    )
    write_wiki_page(
        "concepts/public.md",
        "公开知识页",
        "concept",
        "公开课程材料",
        project_id="p",
    )

    async def stale_vector_hit(*args, **kwargs):
        return [{"path": path, "title": "学习者活动档案", "snippet": "秘密学习主题", "score": 0.99}]

    from services import search_engine

    monkeypatch.setattr(search_engine, "_vector_search", stale_vector_hit)
    from main import app

    client = TestClient(app)
    listed = client.get("/api/wiki/pages?project_id=p").json()
    assert all(page["path"] != path for page in listed)
    assert client.get(f"/api/wiki/pages/{path}?project_id=p").status_code == 404
    assert client.get(f"/api/wiki/pages/{path.replace('/', '%252F')}?project_id=p").status_code == 404
    assert client.put(
        f"/api/wiki/pages/{path}?project_id=p", json={"content": "changed"}
    ).status_code == 404
    assert client.delete(f"/api/wiki/pages/{path}?project_id=p").status_code == 404

    search = client.get(
        "/api/search",
        params={"q": "秘密学习主题", "vector": "true", "project_id": "p"},
    ).json()
    assert all(result["path"] != path for result in search["results"])
    assert search["vector_hits"] == 0
