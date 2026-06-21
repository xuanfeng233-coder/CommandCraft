"""LLMStep：provider 无关的「走一步」抽象。Native=原生工具调用；Prompted=提示式模拟。"""

from __future__ import annotations

import abc
from typing import Any

from backend.agentloop.schemas import Observation, StepResult, ToolCall
from backend.config import AGENT_LOOP_MAX_TOKENS
from backend.utils.providers import get_provider


class LLMStep(abc.ABC):
    @abc.abstractmethod
    async def run(self, messages: list[dict[str, Any]], tool_schemas: list[dict[str, Any]]) -> StepResult: ...

    @abc.abstractmethod
    def format_observation(self, call: ToolCall, obs: Observation) -> dict[str, Any]: ...


class NativeToolStep(LLMStep):
    def __init__(self, client) -> None:
        self._client = client

    async def run(self, messages: list[dict[str, Any]], tool_schemas: list[dict[str, Any]]) -> StepResult:
        resp = await self._client.chat_with_tools(messages, tool_schemas, max_tokens=AGENT_LOOP_MAX_TOKENS)
        msg = resp["message"]
        tool_calls = [
            ToolCall(id=tc["id"], name=tc["function"]["name"], arguments=tc["function"]["arguments"])
            for tc in msg.get("tool_calls", [])
        ]
        return StepResult(
            content=msg.get("content", ""),
            thinking=msg.get("thinking", ""),
            tool_calls=tool_calls,
            raw_assistant_msg=msg,
        )

    def format_observation(self, call: ToolCall, obs: Observation) -> dict[str, Any]:
        return {"role": "tool", "tool_call_id": call.id, "content": obs.to_tool_content()}


class PromptedToolStep(LLMStep):
    """提示式工具调用步骤（Task 4 完整实现 run）。"""

    def __init__(self, client) -> None:
        self._client = client

    async def run(self, messages: list[dict[str, Any]], tool_schemas: list[dict[str, Any]]) -> StepResult:
        raise NotImplementedError("PromptedToolStep.run 将在 Task 4 实现")

    def format_observation(self, call: ToolCall, obs: Observation) -> dict[str, Any]:
        return {"role": "user", "content": f"[工具 {call.name} 返回]\n{obs.to_tool_content()}"}


def build_step(client) -> LLMStep:
    """根据 provider 能力选择 Native 或 Prompted 步骤（None→乐观 Native）。"""
    provider = get_provider(getattr(client, "provider_id", ""))
    supports = getattr(provider, "supports_tools", True) if provider else True
    if supports:
        return NativeToolStep(client)
    return PromptedToolStep(client)
