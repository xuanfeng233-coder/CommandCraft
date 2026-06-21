import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.settings as settings_module


def _client():
    app = FastAPI()
    app.include_router(settings_module.router)
    return TestClient(app)


def test_verify_rejects_internal_base_url(monkeypatch):
    # base_url 解析到内网 → 预校验拒，不真正发健康检查
    monkeypatch.setattr("backend.llm.url_guard._resolve_host", lambda host, port: ["127.0.0.1"])
    called = {"n": 0}

    async def _health():
        called["n"] += 1
        return True, True

    from backend.utils.llm_client import llm_client
    monkeypatch.setattr(llm_client, "check_health", _health)

    resp = _client().post("/api/settings/verify", json={
        "provider_id": "custom", "api_key": "k", "base_url": "http://127.0.0.1:8003/v1", "model": "m",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "受限" in body["error"] or "地址" in body["error"]
    assert called["n"] == 0  # 健康检查未被调用（SSRF 在发起前被拦）


def test_verify_allows_public_base_url(monkeypatch):
    monkeypatch.setattr("backend.llm.url_guard._resolve_host", lambda host, port: ["93.184.216.34"])

    async def _health():
        return True, True

    from backend.utils.llm_client import llm_client
    monkeypatch.setattr(llm_client, "check_health", _health)

    resp = _client().post("/api/settings/verify", json={
        "provider_id": "deepseek", "api_key": "k", "base_url": "https://api.deepseek.com", "model": "deepseek-chat",
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
