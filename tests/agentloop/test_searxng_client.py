import httpx
import respx

from backend.agentloop.searxng_client import SearXNGClient, WebHit


def _patch_resolver(monkeypatch, ip="127.0.0.1"):
    monkeypatch.setattr("backend.llm.url_guard._resolve_host", lambda host, port: [ip])


@respx.mock
async def test_search_parses_results(monkeypatch):
    _patch_resolver(monkeypatch)
    respx.get("http://127.0.0.1:8888/search").mock(
        return_value=httpx.Response(200, json={"results": [
            {"title": "T1", "url": "https://a", "content": "片段1", "engine": "ddg"},
            {"title": "T2", "url": "https://b", "content": "片段2"},
        ]})
    )
    client = SearXNGClient("http://127.0.0.1:8888", max_results=5)
    hits = await client.search("红石")
    assert [h.title for h in hits] == ["T1", "T2"]
    assert hits[0].url == "https://a" and hits[0].snippet == "片段1"
    assert isinstance(hits[0], WebHit)


@respx.mock
async def test_search_caps_max_results(monkeypatch):
    _patch_resolver(monkeypatch)
    respx.get("http://127.0.0.1:8888/search").mock(
        return_value=httpx.Response(200, json={"results": [
            {"title": f"T{i}", "url": f"https://{i}", "content": ""} for i in range(10)
        ]})
    )
    client = SearXNGClient("http://127.0.0.1:8888", max_results=3)
    hits = await client.search("x")
    assert len(hits) == 3


@respx.mock
async def test_timeout_returns_empty(monkeypatch):
    _patch_resolver(monkeypatch)
    respx.get("http://127.0.0.1:8888/search").mock(side_effect=httpx.ConnectTimeout("slow"))
    client = SearXNGClient("http://127.0.0.1:8888")
    assert await client.search("x") == []


@respx.mock
async def test_non_200_returns_empty(monkeypatch):
    _patch_resolver(monkeypatch)
    respx.get("http://127.0.0.1:8888/search").mock(return_value=httpx.Response(502))
    client = SearXNGClient("http://127.0.0.1:8888")
    assert await client.search("x") == []


async def test_unsafe_url_returns_empty(monkeypatch):
    # base_url 解析到公网外的私有地址（非环回）→ url_guard 拒 → []
    monkeypatch.setattr("backend.llm.url_guard._resolve_host", lambda host, port: ["10.0.0.5"])
    client = SearXNGClient("http://internal.evil/")
    assert await client.search("x") == []


def test_get_client_disabled_when_no_url(monkeypatch):
    import backend.agentloop.searxng_client as mod
    monkeypatch.setattr(mod, "SEARXNG_URL", "")
    # 强制重置单例缓存
    mod._client_singleton = None
    mod._client_resolved = False
    assert mod.get_searxng_client() is None
