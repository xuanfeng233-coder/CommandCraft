"""AgentLoop: 统一 Agent 循环，驱动 model step → tool dispatch → observation → continue。

终止条件：
- finish 工具调用（done / ask_user / give_up）
- 隐式完成（StepResult 无工具调用）
- 预算耗尽（达到 max_rounds 上限）
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator

from backend.agentloop.schemas import (
    AgentOutcome,
    FinishReason,
    LoopBudget,
    Observation,
)
from backend.agentloop.tools.registry import ToolContext, ToolRegistry

logger = logging.getLogger(__name__)

_REASON_MAP: dict[str, FinishReason] = {
    "done": FinishReason.DONE,
    "ask_user": FinishReason.ASK_USER,
    "give_up": FinishReason.GIVE_UP,
}


class AgentLoop:
    """统一 Agent 循环。

    run(messages) 是 async generator：
    - yield {"event": "thinking", "data": {"text": ...}}  (当 thinking 非空时)
    - yield {"event": "_agent_outcome", "data": {"outcome": AgentOutcome}}  (最终)
    并同时设 self.last_outcome。
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        step,  # LLMStep（或任意实现 run/format_observation 的对象）
        budget: LoopBudget,
        edition: str,
    ) -> None:
        self._registry = registry
        self._step = step
        self._budget = budget
        self._edition = edition
        self.last_outcome: AgentOutcome | None = None

    async def run(
        self, messages: list[dict[str, Any]]
    ) -> AsyncGenerator[dict[str, Any], None]:
        # ── 每次 run() 构造全新 ctx，不复用，counters 不跨请求泄漏 ──
        ctx = ToolContext(
            edition=self._edition,
            budget=self._budget,
            counters={},
        )

        budget = self._budget
        registry = self._registry

        # 工作消息列表：在本次 run 内增长，不修改调用方的 list
        msgs = list(messages)

        thinking_parts: list[str] = []
        observations: list[Observation] = []
        finish_reason: FinishReason | None = None
        finish_content: str = ""
        rounds_used: int = 0

        for round_idx in range(budget.max_rounds):
            rounds_used = round_idx + 1

            sr = await self._step.run(msgs, registry.get_schemas())

            # ── thinking 累积 ──
            if sr.thinking:
                if thinking_parts:
                    thinking_parts.append("---")
                thinking_parts.append(sr.thinking)
                yield {"event": "thinking", "data": {"text": sr.thinking}}

            # ── 隐式完成：无工具调用 ──
            if not sr.tool_calls:
                finish_reason = FinishReason.IMPLICIT_DONE
                finish_content = sr.content
                break

            # 把 assistant 消息追加到工作列表
            msgs.append(sr.raw_assistant_msg)

            # ── 逐工具执行，finish 优先检测 ──
            finish_found = False
            for call in sr.tool_calls:
                if call.name == "finish":
                    # 执行 finish handler 以获取 data（data 已在 Observation.data 里）
                    obs = await registry.execute(call.name, call.arguments, ctx)
                    observations.append(obs)
                    data = obs.data if obs.data else {}
                    raw_reason = data.get("reason", call.arguments.get("reason", "done"))
                    finish_reason = _REASON_MAP.get(str(raw_reason), FinishReason.DONE)
                    finish_content = data.get(
                        "final_answer",
                        call.arguments.get("final_answer", ""),
                    )
                    finish_found = True
                    break  # 跳出工具循环

                obs = await registry.execute(call.name, call.arguments, ctx)
                observations.append(obs)
                msgs.append(self._step.format_observation(call, obs))

            if finish_found:
                break

            # ── 预算警告 ──
            if round_idx + 1 == budget.warn_at_round:
                msgs.append(
                    {"role": "user", "content": budget.warning_text(round_idx + 1)}
                )

        else:
            # ── 预算耗尽：for 循环正常结束，未 break ──
            sr_final = await self._step.run(msgs, [])
            if sr_final.thinking:
                if thinking_parts:
                    thinking_parts.append("---")
                thinking_parts.append(sr_final.thinking)
                yield {"event": "thinking", "data": {"text": sr_final.thinking}}
            finish_reason = FinishReason.BUDGET_EXHAUSTED
            finish_content = sr_final.content

        thinking_text = "\n".join(thinking_parts)
        outcome = AgentOutcome(
            reason=finish_reason or FinishReason.IMPLICIT_DONE,
            content=finish_content,
            thinking=thinking_text,
            observations=observations,
            rounds_used=rounds_used,
        )
        self.last_outcome = outcome
        yield {"event": "_agent_outcome", "data": {"outcome": outcome}}
