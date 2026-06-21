"""工具注册表：统一注册/分发工具，并把 handler 异常转成 Observation（绝不外抛）。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from backend.agentloop.schemas import LoopBudget, Observation

logger = logging.getLogger(__name__)

ToolHandler = Callable[[dict[str, Any], "ToolContext"], Awaitable[Observation]]


@dataclass
class ToolContext:
    edition: str
    budget: LoopBudget
    counters: dict[str, int]


@dataclass
class RegisteredTool:
    schema: dict[str, Any]
    handler: ToolHandler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, schema: dict[str, Any], handler: ToolHandler) -> None:
        name = schema["function"]["name"]
        self._tools[name] = RegisteredTool(schema=schema, handler=handler)

    def get_schemas(self) -> list[dict[str, Any]]:
        return [t.schema for t in self._tools.values()]

    def names(self) -> set[str]:
        return set(self._tools.keys())

    async def execute(
        self, name: str, args: dict[str, Any], ctx: "ToolContext"
    ) -> Observation:
        tool = self._tools.get(name)
        if tool is None:
            return Observation(tool_name=name, ok=False, summary="", error=f"未知工具: {name}")
        try:
            return await tool.handler(args, ctx)
        except Exception as exc:  # noqa: BLE001 - 工具错误转 Observation，循环不崩
            logger.warning("工具 %s 执行异常：%s", name, exc)
            return Observation(
                tool_name=name, ok=False,
                summary=f"工具 {name} 执行失败",
                error=str(exc),
            )
