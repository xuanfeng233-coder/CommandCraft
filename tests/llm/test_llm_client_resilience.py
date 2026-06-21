import types

import httpx
import pytest

from backend.llm.errors import PermanentLLMError
from backend.utils.llm_client import LLMClient


def _fake_response(content: str):
    message = types.SimpleNamespace(content=content, tool_calls=None)
    choice = types.SimpleNamespace(message=message)
    return types.SimpleNamespace(choices=[choice])


class _FakeCompletions:
    """按脚本逐次返回结果或抛异常。"""

    def __init__(self, script: list):
        self._script = script
        self.calls = 0

    async def create(self, **kwargs):
        item = self._script[self.calls]
        self.calls += 1
        if isinstance(item, BaseException):
            raise item
        return item


def _install_fake(client: LLMClient, script: list) -> _FakeCompletions:
    fake = _FakeCompletions(script)
    client._client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=fake)
    )
    client._model = "test-model"
    client._provider_id = "test"
    client._thinking_field = ""
    return fake


@pytest.fixture(autouse=True)
def _instant_sleep(monkeypatch):
    async def _no_sleep(_d):
        return None

    monkeypatch.setattr("backend.llm.retry.asyncio.sleep", _no_sleep)


async def test_chat_retries_transient_then_succeeds():
    client = LLMClient()
    fake = _install_fake(
        client,
        [httpx.ConnectError("refused"), _fake_response("hello")],
    )
    out = await client.chat([{"role": "user", "content": "hi"}])
    assert out["message"]["content"] == "hello"
    assert fake.calls == 2


async def test_chat_raises_permanent_immediately():
    client = LLMClient()
    fake = _install_fake(client, [ValueError("bad")])
    with pytest.raises(PermanentLLMError):
        await client.chat([{"role": "user", "content": "hi"}])
    assert fake.calls == 1
