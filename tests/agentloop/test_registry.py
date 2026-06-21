import pytest

from backend.agentloop.schemas import LoopBudget, Observation
from backend.agentloop.tools.registry import ToolContext, ToolRegistry


def _ctx():
    return ToolContext(edition="bedrock", budget=LoopBudget(), counters={})


def _schema(name):
    return {"type": "function", "function": {"name": name, "description": "d", "parameters": {"type": "object", "properties": {}}}}


async def test_register_and_execute():
    reg = ToolRegistry()

    async def handler(args, ctx):
        return Observation(tool_name="t", ok=True, summary=f"got {args.get('x')}")

    reg.register(_schema("t"), handler)
    assert reg.names() == {"t"}
    assert reg.get_schemas() == [_schema("t")]
    obs = await reg.execute("t", {"x": 5}, _ctx())
    assert obs.ok and "got 5" in obs.summary


async def test_unknown_tool_returns_error_observation():
    reg = ToolRegistry()
    obs = await reg.execute("nope", {}, _ctx())
    assert obs.ok is False
    assert "未知工具" in (obs.error or "")


async def test_handler_exception_becomes_observation():
    reg = ToolRegistry()

    async def boom(args, ctx):
        raise RuntimeError("explode")

    reg.register(_schema("b"), boom)
    obs = await reg.execute("b", {}, _ctx())
    assert obs.ok is False
    assert "explode" in (obs.error or "")
    assert obs.tool_name == "b"
