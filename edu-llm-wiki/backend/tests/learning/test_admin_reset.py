"""Integration test for the admin reset endpoint."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _build_client(projects_dir: str):
    from config import settings  # local import so monkeypatch is applied first
    from main import app
    return TestClient(app), settings


def test_reset_user_endpoint_clears_v3_tables(monkeypatch, tmp_path):
    monkeypatch.setattr("config.settings.projects_dir", str(tmp_path))
    monkeypatch.setattr("config.settings.api_token", "")
    client, _ = _build_client(str(tmp_path))

    from services.graph_store import ensure_schema
    ensure_schema("default")

    from services.mastery import record_attempt
    record_attempt("default", "u1", "kcA", score=1, max_score=1, confidence=4, response="忘了", expected="x")
    record_attempt("default", "u1", "kcA", score=0, max_score=1, confidence=5, response="错了", expected="y")

    r = client.post("/api/graph/admin/reset-user?project_id=default&user_id=u1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["user_id"] == "u1"
    deleted = body["deleted"]
    assert deleted.get("bkt_params", 0) >= 1
    assert deleted.get("sr_schedule", 0) >= 1
    assert deleted.get("confidence_log", 0) >= 1
    assert deleted.get("attempts_raw", 0) >= 2
    assert deleted.get("misconception_traces", 0) >= 1


def test_reset_user_requires_admin_token_when_configured(monkeypatch, tmp_path):
    monkeypatch.setattr("config.settings.projects_dir", str(tmp_path))
    monkeypatch.setattr("config.settings.api_token", "secret")
    client, _ = _build_client(str(tmp_path))

    r = client.post("/api/graph/admin/reset-user?project_id=default&user_id=u1")
    assert r.status_code == 401
    assert r.json()["detail"] == "admin_token missing or invalid"

    r = client.post(
        "/api/graph/admin/reset-user?project_id=default&user_id=u1&admin_token=wrong"
    )
    assert r.status_code == 401

    r = client.post(
        "/api/graph/admin/reset-user?project_id=default&user_id=u1&admin_token=secret"
    )
    assert r.status_code == 200
