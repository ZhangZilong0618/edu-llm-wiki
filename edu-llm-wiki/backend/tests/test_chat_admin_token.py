"""Tests for the chat admin-token gate."""

from config import settings
from fastapi.testclient import TestClient
from routes import chat as chat_routes


def _client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))

    async def fake_chat_complete(**kwargs):
        return "mocked chat response"

    monkeypatch.setattr(chat_routes, "chat_complete", fake_chat_complete)
    from main import app
    return TestClient(app)


def test_chat_open_when_no_api_token(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "api_token", "")
    client = _client(monkeypatch, tmp_path)
    resp = client.post(
        "/api/chat?project_id=default",
        json={"messages": [{"role": "user", "content": "hi"}], "context_budget": 8000},
    )
    # Either 200 (with greeting / streaming) or any non-401: we just need
    # the gate to be open in local-dev mode.
    assert resp.status_code != 401, resp.text


def test_chat_rejects_wrong_token(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "api_token", "secret")
    client = _client(monkeypatch, tmp_path)
    resp = client.post(
        "/api/chat?project_id=default&admin_token=wrong",
        json={"messages": [{"role": "user", "content": "hi"}], "context_budget": 8000},
    )
    assert resp.status_code == 401
    assert "admin_token" in resp.json()["detail"]


def test_chat_accepts_correct_token_query(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "api_token", "secret")
    client = _client(monkeypatch, tmp_path)
    resp = client.post(
        "/api/chat?project_id=default&admin_token=secret",
        json={"messages": [{"role": "user", "content": "hi"}], "context_budget": 8000},
    )
    assert resp.status_code != 401


def test_chat_accepts_header_token(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "api_token", "secret")
    client = _client(monkeypatch, tmp_path)
    resp = client.post(
        "/api/chat?project_id=default",
        headers={"X-Admin-Token": "secret"},
        json={"messages": [{"role": "user", "content": "hi"}], "context_budget": 8000},
    )
    assert resp.status_code != 401


def test_chat_stream_rejects_bad_token(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "api_token", "secret")
    client = _client(monkeypatch, tmp_path)
    resp = client.post(
        "/api/chat/stream?project_id=default&admin_token=wrong",
        json={"messages": [{"role": "user", "content": "hi"}], "context_budget": 8000},
    )
    assert resp.status_code == 401


def test_chat_stream_greeting_provider_error_ends_sse_cleanly(monkeypatch, tmp_path):
    """A provider failure must still yield an error event and ``[DONE]``."""
    monkeypatch.setattr(settings, "api_token", "")
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))

    async def broken_stream(**kwargs):
        raise RuntimeError("provider unavailable")
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(chat_routes, "stream_chat", broken_stream)
    from main import app

    client = TestClient(app)
    resp = client.post(
        "/api/chat/stream?project_id=default",
        json={"messages": [{"role": "user", "content": "你好"}]},
    )
    assert resp.status_code == 200
    assert '"type": "error"' in resp.text
    assert "[DONE]" in resp.text


def test_chat_nonstream_provider_error_returns_actionable_status(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "api_token", "")
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))

    async def broken_chat(**kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(chat_routes, "chat_complete", broken_chat)
    from main import app

    client = TestClient(app)
    resp = client.post(
        "/api/chat?project_id=default",
        json={"messages": [{"role": "user", "content": "你好"}]},
    )
    assert resp.status_code == 502
    assert "生成中断" in resp.json()["detail"]
