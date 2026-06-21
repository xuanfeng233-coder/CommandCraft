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
    """对 supports_tools=False 的 provider，用提示式 JSON 协议模拟工具调用。"""

    def __init__(self, client) -> None:
        self._client = client
        self._round = 0
        self._protocol_injected = False  # 实例属性记注入状态，避免污染 message dict

    async def run(self, messages: list[dict[str, Any]], tool_schemas: list[dict[str, Any]]) -> StepResult:
        from backend.skills.base import BaseSkill

        msgs = self._ensure_protocol(messages, tool_schemas)
        resp = await self._client.chat(msgs, max_tokens=AGENT_LOOP_MAX_TOKENS)
        msg = resp["message"]
        content = msg.get("content", "")
        thinking = msg.get("thinking", "")
        data = BaseSkill.extract_json(content)
        tool_calls: list[ToolCall] = []
        if isinstance(data, dict) and data.get("tool"):
            tool_calls = [ToolCall(
                id=f"prompted-{self._round}",
                name=str(data["tool"]),
                arguments=data.get("arguments", {}) if isinstance(data.get("arguments"), dict) else {},
            )]
            self._round += 1
        return StepResult(
            content=content,
            thinking=thinking,
            tool_calls=tool_calls,
            raw_assistant_msg={"role": "assistant", "content": content},
        )

    def _ensure_protocol(self, messages: list[dict[str, Any]], tool_schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """注入工具协议前导到 system message（仅注入一次，用实例属性追踪状态）。"""
        if self._protocol_injected:
            return messages
        manifest_lines = [
            "你可使用以下工具。若需调用，仅输出 JSON：{\"tool\":\"<名称>\",\"arguments\":{...}}；"
            "若已得最终答案，直接输出最终结果（不要包工具 JSON）。可用工具："
        ]
        for s in tool_schemas:
            fn = s.get("function", {})
            manifest_lines.append(f"- {fn.get('name')}: {fn.get('description', '')}")
        manifest = "\n".join(manifest_lines)
        new = list(messages)
        if new and new[0].get("role") == "system":
            new[0] = {**new[0], "content": new[0]["content"] + "\n\n" + manifest}
        else:
            new.insert(0, {"role": "system", "content": manifest})
        self._protocol_injected = True
        return new

    def format_observation(self, call: ToolCall, obs: Observation) -> dict[str, Any]:
        return {"role": "user", "content": f"[工具 {call.name} 返回]\n{obs.to_tool_content()}"}


def build_step(client) -> LLMStep:
    """根据 provider 能力选择 Native 或 Prompted 步骤（None→乐观 Native）。"""
    provider = get_provider(getattr(client, "provider_id", ""))
    supports = getattr(provider, "supports_tools", True) if provider else True
    if supports:
        return NativeToolStep(client)
    return PromptedToolStep(client)
