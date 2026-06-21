import pytest

from backend.agents.planner import Planner, PlannerParseError
from backend.llm.errors import PermanentLLMError, TransientLLMError

VALID = '{"is_single_task": false, "tasks": [{"task_id":"1","description":"d","user_request":"u","depends_on":[]},{"task_id":"2","description":"e","user_request":"v","depends_on":["1"]}]}'
CYCLE = '{"tasks":[{"task_id":"1","depends_on":["2"]},{"task_id":"2","depends_on":["1"]}]}'


class FakeClient:
    def __init__(self, script):
        self._script = script
        self.calls = 0
        self.last_messages = None

    async def chat(self, messages, *, max_tokens=None, think=None):
        self.last_messages = messages
        item = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return {"message": {"role": "assistant", "content": item, "thinking": "想"}}


async def test_happy_path_once():
    c = FakeClient([VALID])
    d, thinking = await Planner().plan("造个东西", client=c)
    assert [t.id for t in d.tasks] == ["1", "2"]
    assert thinking == "想"
    assert c.calls == 1


async def test_repair_once_then_clean():
    c = FakeClient([CYCLE, VALID])
    d, _ = await Planner().plan("x", client=c)
    assert [t.id for t in d.tasks] == ["1", "2"]
    assert c.calls == 2
    # 第二次调用的消息里含环错误反馈
    assert any("循环" in m.get("content", "") for m in c.last_messages)


async def test_repair_exhausted_raises_not_fallback():
    c = FakeClient([CYCLE, CYCLE, CYCLE])
    with pytest.raises(PlannerParseError):
        await Planner().plan("x", client=c, max_repairs=2)
    assert c.calls == 3  # 1 + 2


async def test_transport_transient_propagates_no_repair():
    c = FakeClient([TransientLLMError("net")])
    with pytest.raises(TransientLLMError):
        await Planner().plan("x", client=c)
    assert c.calls == 1  # 不进修复


async def test_transport_permanent_propagates():
    c = FakeClient([PermanentLLMError("auth")])
    with pytest.raises(PermanentLLMError):
        await Planner().plan("x", client=c)


async def test_non_json_then_json_repairs():
    c = FakeClient(["这是一段废话不是JSON", VALID])
    d, _ = await Planner().plan("x", client=c)
    assert len(d.tasks) == 2
    assert c.calls == 2
    assert any("JSON" in m.get("content", "") for m in c.last_messages)


async def test_java_edition_uses_java_prompt():
    c = FakeClient([VALID])
    await Planner().plan("x", client=c, edition="java")
    sys_content = c.last_messages[0]["content"]
    assert "Java" in sys_content or "/data" in sys_content
