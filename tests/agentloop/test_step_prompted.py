from backend.agentloop.schemas import Observation, ToolCall
from backend.agentloop.step import PromptedToolStep


class _PlainClient:
    provider_id = "glm"

    def __init__(self, text):
        self._text = text

    async def chat(self, messages, *, max_tokens=None):
        return {"message": {"role": "assistant", "content": self._text, "thinking": ""}}


async def test_prompted_parses_tool_json():
    c = _PlainClient('{"tool":"get_command_usage","arguments":{"command_name":"give"}}')
    sr = await PromptedToolStep(c).run([{"role": "user", "content": "x"}], [])
    assert len(sr.tool_calls) == 1
    assert sr.tool_calls[0].name == "get_command_usage"
    assert sr.tool_calls[0].arguments == {"command_name": "give"}
    assert sr.tool_calls[0].id.startswith("prompted-")


async def test_prompted_final_answer_no_tool():
    c = _PlainClient('{"type":"single_command","command":{"command":"/say hi"}}')
    sr = await PromptedToolStep(c).run([{"role": "user", "content": "x"}], [])
    assert sr.tool_calls == []
    assert "single_command" in sr.content


def test_prompted_format_observation_folds_to_user():
    step = PromptedToolStep(_PlainClient(""))
    msg = step.format_observation(ToolCall("p-0", "search_wiki", {}), Observation("search_wiki", True, "命中"))
    assert msg["role"] == "user"
    assert "search_wiki" in msg["content"] and "命中" in msg["content"]
