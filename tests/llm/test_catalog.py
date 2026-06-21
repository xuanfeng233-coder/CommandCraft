import logging
import httpx
import pytest
import respx

from backend.llm.catalog import ModelCatalog, ModelInfo


def _clock():
    state = {"t": 0.0}

    def now():
        return state["t"]

    return state, now


async def test_dynamic_fetch_sets_source_dynamic():
    async def fetcher(base_url, api_key):
        return ["m-a", "m-b"]

    cat = ModelCatalog(fetcher=fetcher)
    out = await cat.list_models("deepseek", api_key="k", base_url="https://api/v1")
    assert [m.id for m in out] == ["m-a", "m-b"]
    assert all(m.source == "dynamic" for m in out)
    assert all(isinstance(m, ModelInfo) for m in out)


async def test_fetch_failure_falls_back_to_curated():
    async def fetcher(base_url, api_key):
        raise httpx.ConnectError("refused")

    cat = ModelCatalog(fetcher=fetcher)
    out = await cat.list_models("deepseek", api_key="k", base_url="https://api/v1")
    ids = [m.id for m in out]
    assert "deepseek-chat" in ids
    assert all(m.source == "curated" for m in out)


async def test_missing_credentials_uses_curated_without_fetch():
    called = {"n": 0}

    async def fetcher(base_url, api_key):
        called["n"] += 1
        return ["should-not-happen"]

    cat = ModelCatalog(fetcher=fetcher)
    out = await cat.list_models("deepseek", api_key="", base_url="")
    assert called["n"] == 0
    assert all(m.source == "curated" for m in out)


async def test_missing_credentials_logs_warning(caplog):
    async def fetcher(base_url, api_key):
        return ["should-not-happen"]

    cat = ModelCatalog(fetcher=fetcher)
    with caplog.at_level(logging.WARNING):
        out = await cat.list_models("deepseek", api_key="", base_url="")
    assert all(m.source == "curated" for m in out)
    assert any("回落 curated 模型列表" in r.message for r in caplog.records)


async def test_cache_hit_within_ttl():
    calls = {"n": 0}

    async def fetcher(base_url, api_key):
        calls["n"] += 1
        return ["m-a"]

    state, now = _clock()
    cat = ModelCatalog(fetcher=fetcher, ttl=100, time_fn=now)
    await cat.list_models("deepseek", api_key="k", base_url="https://api/v1")
    state["t"] = 50  # < ttl
    await cat.list_models("deepseek", api_key="k", base_url="https://api/v1")
    assert calls["n"] == 1  # 第二次命中缓存


async def test_cache_expires_after_ttl():
    calls = {"n": 0}

    async def fetcher(base_url, api_key):
        calls["n"] += 1
        return ["m-a"]

    state, now = _clock()
    cat = ModelCatalog(fetcher=fetcher, ttl=100, time_fn=now)
    await cat.list_models("deepseek", api_key="k", base_url="https://api/v1")
    state["t"] = 150  # > ttl
    await cat.list_models("deepseek", api_key="k", base_url="https://api/v1")
    assert calls["n"] == 2


@respx.mock
async def test_httpx_fetcher_parses_openai_shape(monkeypatch):
    # SSRF 守卫用真实 DNS 解析 api.test.local 会失败，这里让它解析到公网 IP
    monkeypatch.setattr(
        "backend.llm.url_guard._resolve_host", lambda host, port: ["1.2.3.4"]
    )
    route = respx.get("https://api.test.local/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "x-1"}, {"id": "x-2"}]})
    )
    cat = ModelCatalog()
    ids = await cat._httpx_fetch_models("https://api.test.local/v1", "secret")
    assert ids == ["x-1", "x-2"]
    assert route.called
    # 带上 Authorization 头
    assert route.calls.last.request.headers["authorization"] == "Bearer secret"


async def test_httpx_fetcher_blocks_internal_url():
    # SSRF 防护：指向 loopback 的 base_url 在发起请求前被拒绝
    from backend.llm.url_guard import UnsafeURLError

    cat = ModelCatalog()
    with pytest.raises(UnsafeURLError):
        await cat._httpx_fetch_models("http://127.0.0.1:8003/v1", "k")
