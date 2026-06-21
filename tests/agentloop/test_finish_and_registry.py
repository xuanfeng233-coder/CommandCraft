import pytest

from backend.agentloop.schemas import LoopBudget
from backend.agentloop.tools.finish import build_default_registry, register_finish_tool
from backend.agentloop.tools.registry import ToolContext, ToolRegistry


def _ctx():
    return ToolContext(edition="bedrock", budget=LoopBudget(), counters={})


async def test_finish_normalizes_done():
    reg = ToolRegistry()
    register_finish_tool(reg)
    obs = await reg.execute("finish", {"reason": "done", "final_answer": "/give @p diamond"}, _ctx())
    assert obs.data["reason"] == "done"
    assert obs.data["final_answer"] == "/give @p diamond"


async def test_finish_invalid_reason_falls_back_giveup():
    reg = ToolRegistry()
    register_finish_tool(reg)
    obs = await reg.execute("finish", {"reason": "nonsense", "final_answer": "x"}, _ctx())
    assert obs.data["reason"] == "give_up"


def test_build_default_registry_has_seven_tools():
    reg = build_default_registry()
    assert reg.names() == {
        "get_command_usage", "get_parameter_options", "get_formatting_codes",
        "search_wiki", "validate_command", "search_web", "finish",
    }
    # get_schemas 与 chat_with_tools 的 tools= 形状兼容
    schemas = reg.get_schemas()
    assert len(schemas) == 7
    assert all(s["type"] == "function" and "name" in s["function"] for s in schemas)


async def test_build_default_registry_dispatches_finish():
    reg = build_default_registry()
    obs = await reg.execute("finish", {"reason": "ask_user", "final_answer": "你想要钻石剑还是铁剑？"}, _ctx())
    assert obs.data["reason"] == "ask_user"
