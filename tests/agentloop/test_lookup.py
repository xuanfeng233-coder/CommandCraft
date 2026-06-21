import pytest

from backend.agentloop.schemas import LoopBudget, Observation
from backend.agentloop.tools.lookup import register_lookup_tools
from backend.agentloop.tools.registry import ToolContext, ToolRegistry


def _ctx(edition="bedrock"):
    return ToolContext(edition=edition, budget=LoopBudget(), counters={})


def _reg():
    reg = ToolRegistry()
    register_lookup_tools(reg)
    return reg


def test_registers_four_wire_names():
    reg = _reg()
    assert {"get_command_usage", "get_parameter_options", "get_formatting_codes", "search_wiki"} <= reg.names()


async def test_get_command_usage_known_command_bedrock():
    obs = await _reg().execute("get_command_usage", {"command_name": "give"}, _ctx("bedrock"))
    assert isinstance(obs.to_tool_content(), str)
    # give 是基岩版核心命令，应能查到（summary 含命令名）
    assert obs.ok is True
    assert "give" in obs.summary.lower()


async def test_get_command_usage_unknown_is_not_ok():
    obs = await _reg().execute("get_command_usage", {"command_name": "zzznotacommand"}, _ctx("bedrock"))
    assert obs.ok is False
    assert "未找到" in obs.summary or (obs.error and "未找到" in obs.error)


async def test_get_parameter_options_filters():
    obs = await _reg().execute("get_parameter_options", {"category": "items", "search_term": "sword"}, _ctx("bedrock"))
    assert isinstance(obs.to_tool_content(), str)
    assert obs.tool_name == "get_parameter_options"


async def test_edition_routing_java_loader_used(monkeypatch):
    # 断言 handler 用的是 get_loader(ctx.edition) 而非 bedrock 单例
    import backend.agentloop.tools.lookup as lookup_mod

    captured = {}

    class _FakeLoader:
        def get_command_doc(self, name):
            captured["edition_doc"] = name
            return {"name": name}

        def format_command_docs_compact(self, names):
            return f"[fake-java] {names[0]}"

    monkeypatch.setattr(lookup_mod, "get_loader", lambda edition: _FakeLoader() if edition == "java" else (_ for _ in ()).throw(AssertionError("应使用 java loader")))
    obs = await _reg().execute("get_command_usage", {"command_name": "give"}, _ctx("java"))
    assert "[fake-java]" in obs.summary


async def test_get_formatting_codes():
    obs = await _reg().execute("get_formatting_codes", {}, _ctx("bedrock"))
    assert isinstance(obs.to_tool_content(), str)
    assert obs.tool_name == "get_formatting_codes"
