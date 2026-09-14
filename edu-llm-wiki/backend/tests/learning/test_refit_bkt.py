"""Integration tests for the /admin/refit-bkt endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from config import settings
from services.graph_store import ensure_schema
from services.mastery import record_attempt
from storage.wiki_store import ensure_dirs


def _client(monkeypatch, tmp_path, *, api_token: str = ""):
    monkeypatch.setattr(settings, "projects_dir", str(tmp_path))
    monkeypatch.setattr(settings, "api_token", api_token)
    from main import app
    return TestClient(app)


def test_refit_rejects_when_data_insufficient(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    ensure_schema("default")
    ensure_dirs(project_id="default")
    # Only 2 attempts (below min_observations=5)
    record_attempt("default", "u1", "kcA", score=1, max_score=1, confidence=4)
    record_attempt("default", "u1", "kcA", score=0, max_score=1, confidence=3)
    r = client.post("/api/graph/admin/refit-bkt?project_id=default&user_id=u1")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "insufficient_data"
    assert body["observations"] == 2


def test_refit_succeeds_with_enough_data(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    ensure_schema("default")
    ensure_dirs(project_id="default")
    # Mix of correct and incorrect across a couple KCs, enough to fit.
    for i in range(6):
        score = 1.0 if i % 2 == 0 else 0.0
        record_attempt("default", "u1", f"kc{i % 2}", score=score, max_score=1, confidence=4 if score > 0.5 else 2)
    r = client.post("/api/graph/admin/refit-bkt?project_id=default&user_id=u1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["observations"] == 6
    # Fitted parameters live in [0, 1].
    for k in ("p_known", "p_t", "p_g", "p_s"):
        v = body["params"][k]
        assert 0 < v < 1, f"{k}={v} out of (0, 1)"


def test_refit_requires_admin_token_when_configured(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path, api_token="secret")
    ensure_schema("default")
    r = client.post("/api/graph/admin/refit-bkt?project_id=default&user_id=u1")
    assert r.status_code == 401
    r = client.post("/api/graph/admin/refit-bkt?project_id=default&user_id=u1&admin_token=secret")
    assert r.status_code == 200
