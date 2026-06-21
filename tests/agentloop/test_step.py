import types

from backend.agentloop.schemas import Observation, ToolCall
from backend.agentloop.step import NativeToolStep, PromptedToolStep, build_step


class _NativeClient:
    provider_id = "deepseek"

    def __init__(self, msg):
        self._msg = msg

    async def chat_with_tools(self, messages, tools, *, max_tokens=None):
        return {"message": self._msg}


async def test_native_maps_tool_calls():
    msg = {"role": "assistant", "content": "", "thinking": "想",
           "tool_calls": [{"id": "c1", "type": "function",
                           "function": {"name": "get_command_usage", "arguments": {"command_name": "give"}}}]}
    sr = await NativeToolStep(_NativeClient(msg)).run([], [])
    assert sr.tool_calls[0].id == "c1"
    assert sr.tool_calls[0].name == "get_command_usage"
    assert sr.tool_calls[0].arguments == {"command_name": "give"}  # dict, 非 str
    assert sr.thinking == "想"
    assert sr.raw_assistant_msg is msg


async def test_native_no_tool_calls():
    sr = await NativeToolStep(_NativeClient({"role": "assistant", "content": "答案", "thinking": ""})).run([], [])
    assert sr.tool_calls == []
    assert sr.content == "答案"


def test_native_format_observation():
    step = NativeToolStep(_NativeClient({}))
    msg = step.format_observation(ToolCall("c1", "x", {}), Observation("x", True, "结果"))
    assert msg == {"role": "tool", "tool_call_id": "c1", "content": "结果"}


def test_build_step_picks_native_for_tool_provider(monkeypatch):
    import backend.agentloop.step as step_mod
    monkeypatch.setattr(step_mod, "get_provider", lambda pid: types.SimpleNamespace(supports_tools=True))
    assert isinstance(build_step(_NativeClient({})), NativeToolStep)


def test_build_step_picks_prompted_for_glm(monkeypatch):
    import backend.agentloop.step as step_mod
    monkeypatch.setattr(step_mod, "get_provider", lambda pid: types.SimpleNamespace(supports_tools=False))
    assert isinstance(build_step(_NativeClient({})), PromptedToolStep)
