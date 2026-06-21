import pytest

import backend.agentloop.tools.search as search_mod
from backend.agentloop.schemas import LoopBudget
from backend.agentloop.searxng_client import WebHit
from backend.agentloop.tools.registry import ToolContext, ToolRegistry
from backend.agentloop.tools.search import register_search_tools


def _ctx(counters=None):
    return ToolContext(edition="bedrock", budget=LoopBudget(max_search_web_calls=2), counters=counters or {})


def _reg():
    reg = ToolRegistry()
    register_search_tools(reg)
    return reg


class _FakeClient:
    def __init__(self, hits):
        self._hits = hits
        self.calls = 0

    async def search(self, query, *, categories=None):
        self.calls += 1
        return self._hits


async def test_search_web_returns_hits(monkeypatch):
    fake = _FakeClient([WebHit("T", "https://a", "片段")])
    monkeypatch.setattr(search_mod, "get_searxng_client", lambda: fake)
    obs = await _reg().execute("search_web", {"query": "红石"}, _ctx())
    assert obs.ok is True
    assert "T" in obs.summary
    assert obs.data["hits"][0]["url"] == "https://a"


async def test_search_web_zero_hits_still_ok(monkeypatch):
    monkeypatch.setattr(search_mod, "get_searxng_client", lambda: _FakeClient([]))
    obs = await _reg().execute("search_web", {"query": "x"}, _ctx())
    assert obs.ok is True
    assert obs.data["hits"] == []


async def test_search_web_disabled(monkeypatch):
    monkeypatch.setattr(search_mod, "get_searxng_client", lambda: None)
    obs = await _reg().execute("search_web", {"query": "x"}, _ctx())
    assert obs.ok is False
    assert "未启用" in obs.summary


async def test_search_web_sub_budget(monkeypatch):
    fake = _FakeClient([WebHit("T", "https://a", "片段")])
    monkeypatch.setattr(search_mod, "get_searxng_client", lambda: fake)
    counters = {}
    ctx = _ctx(counters)
    await _reg().execute("search_web", {"query": "1"}, ctx)
    await _reg().execute("search_web", {"query": "2"}, ctx)
    obs3 = await _reg().execute("search_web", {"query": "3"}, ctx)  # 第 3 次超预算（max=2）
    assert obs3.ok is False
    assert "上限" in obs3.summary
    assert fake.calls == 2  # 第三次未真正调用
