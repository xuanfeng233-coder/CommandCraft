import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.settings as settings_module


def _make_client(monkeypatch, fetcher):
    # 用注入了假 fetcher 的全新 catalog 替换端点引用的单例
    from backend.llm.catalog import ModelCatalog

    monkeypatch.setattr(settings_module, "model_catalog", ModelCatalog(fetcher=fetcher))
    app = FastAPI()
    app.include_router(settings_module.router)
    return TestClient(app)


def test_models_endpoint_dynamic(monkeypatch):
    async def fetcher(base_url, api_key):
        return ["m-a", "m-b"]

    client = _make_client(monkeypatch, fetcher)
    resp = client.post(
        "/api/settings/models",
        json={"provider_id": "deepseek", "api_key": "k", "base_url": "https://api/v1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert [m["id"] for m in body["models"]] == ["m-a", "m-b"]
    assert body["source"] == "dynamic"


def test_models_endpoint_fallback_curated(monkeypatch):
    async def fetcher(base_url, api_key):
        raise RuntimeError("down")

    client = _make_client(monkeypatch, fetcher)
    resp = client.post(
        "/api/settings/models",
        json={"provider_id": "deepseek", "api_key": "k", "base_url": "https://api/v1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "curated"
    assert any(m["id"] == "deepseek-chat" for m in body["models"])
