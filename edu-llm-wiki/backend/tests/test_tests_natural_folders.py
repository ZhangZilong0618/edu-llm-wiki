"""Natural-language test generation and user-defined test folders."""

import asyncio

from models.tests import TestCreateRequest as CreateRequest, TestSession as SessionModel, TestUpdateRequest as UpdateRequest
from routes import tests as test_routes


def test_natural_prompt_overrides_generation_constraints():
    req = CreateRequest(
        natural_prompt="请出10道关于疲劳断裂的应用题，只要选择题和简答题",
        question_count=5,
        question_types=["multiple_choice"],
        difficulty="mixed",
    )

    test_routes._apply_natural_prompt(req)

    assert req.question_count == 10
    assert req.question_types == ["multiple_choice", "short_answer"]
    assert req.difficulty == "application"
    assert "疲劳断裂" in (req.title or "")


def test_folder_names_are_normalized_but_keep_hierarchy():
    assert test_routes._normalize_folder(" 期末复习 / 第二章 ") == "期末复习/第二章"
    assert test_routes._normalize_folder("bad:name/../测试") == "bad-name/测试"
    assert test_routes._normalize_folder("   ") is None


def _page(path: str, title: str, page_type: str = "concept") -> dict:
    return {
        "path": path,
        "title": title,
        "page_type": page_type,
        "sources": [],
        "content": f"{title} 的教学内容。",
    }


def test_candidate_context_ranks_natural_language_topic(monkeypatch):
    fatigue = _page("fatigue.md", "疲劳断裂")
    corrosion = _page("corrosion.md", "腐蚀失效")
    guide = _page("guide.md", "学习指引", "guide")
    pages = [fatigue, corrosion, guide]

    monkeypatch.setattr(
        test_routes,
        "list_wiki_pages",
        lambda project_id: [{"path": page["path"]} for page in pages],
    )
    monkeypatch.setattr(
        test_routes,
        "read_wiki_page",
        lambda path, project_id: next(page for page in pages if page["path"] == path),
    )
    search_queries = []
    monkeypatch.setattr(
        test_routes,
        "keyword_search",
        lambda query, top_k, project_id: search_queries.append(query) or [
            {"path": "corrosion.md", "title": "腐蚀失效", "score": 10},
        ],
    )

    req = CreateRequest(natural_prompt="出5道关于腐蚀失效的题")
    _extracted, context = test_routes._candidate_context(req, "default")

    assert search_queries == ["腐蚀失效"]
    assert context.index("### 腐蚀失效") < context.index("### 疲劳断裂")
    assert "学习指引" not in context


def test_candidate_context_restricts_to_requested_page(monkeypatch):
    fatigue = _page("fatigue.md", "疲劳断裂")
    corrosion = _page("corrosion.md", "腐蚀失效")
    pages = [fatigue, corrosion]

    monkeypatch.setattr(
        test_routes,
        "list_wiki_pages",
        lambda project_id: [{"path": page["path"]} for page in pages],
    )
    monkeypatch.setattr(
        test_routes,
        "read_wiki_page",
        lambda path, project_id: next(page for page in pages if page["path"] == path),
    )

    req = CreateRequest(page_path="fatigue.md")
    _extracted, context = test_routes._candidate_context(req, "default")

    assert "### 疲劳断裂" in context
    assert "### 腐蚀失效" not in context


def test_update_test_moves_folder(monkeypatch):
    session = SessionModel(
        id="abc123",
        title="旧测试",
        questions=[],
        created_at="2026-09-16T00:00:00",
    )
    written = []

    monkeypatch.setattr(test_routes, "_read_session", lambda session_id, project_id: session)
    monkeypatch.setattr(
        test_routes,
        "_write_session",
        lambda value, project_id: written.append(value),
    )

    result = asyncio.run(test_routes.update_test(
        "abc123",
        UpdateRequest(folder="期末复习 / 第二章"),
        project_id="default",
    ))

    assert result.folder == "期末复习/第二章"
    assert written == [session]
