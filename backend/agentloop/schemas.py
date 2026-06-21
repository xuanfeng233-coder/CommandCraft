"""统一 Agent 循环的数据契约（dataclass + Pydantic）。

Observation 是每个工具 handler 的返回；StepResult 是 LLMStep 每轮产出；
AgentOutcome 是循环终止结果；ValidationReport 是 validate_command 工具的结构化报告。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel


@dataclass
class Observation:
    """工具执行的结构化结果。ok=False 表示降级/出错，但仍回喂给模型自我纠正。"""

    tool_name: str
    ok: bool
    summary: str  # 面向 LLM 的文本，进入 {"role":"tool","content": ...}
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_tool_content(self) -> str:
        """序列化为 tool message 的 content 字符串（必须是 str）。"""
        parts = [self.summary] if self.summary else []
        if self.error:
            parts.append(f"[错误] {self.error}")
        if self.data:
            parts.append(
                "[数据] " + json.dumps(self.data, ensure_ascii=False)
            )
        return "\n".join(parts) if parts else "(无内容)"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class StepResult:
    content: str
    thinking: str
    tool_calls: list[ToolCall]
    raw_assistant_msg: dict[str, Any]


@dataclass
class LoopBudget:
    """循环预算。max_rounds 含 validate/finish 往返，故默认比旧的 5 高。"""

    max_rounds: int = 8
    warn_at_round: int = 7
    max_tool_calls: int = 12
    max_search_web_calls: int = 2

    def warning_text(self, rounds_used: int) -> str:
        return (
            f"已用 {rounds_used}/{self.max_rounds} 轮，请尽快调用 finish 给出最终答案。"
        )


class FinishReason(str, Enum):
    DONE = "done"
    ASK_USER = "ask_user"
    GIVE_UP = "give_up"
    IMPLICIT_DONE = "implicit_done"
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass
class AgentOutcome:
    reason: FinishReason
    content: str
    thinking: str
    observations: list[Observation]
    rounds_used: int
    error: str | None = None


class ValidationIssue(BaseModel):
    command: str
    type: str
    message: str
    suggestion: str = ""
    severity: Literal["error", "warning"]


class ValidationReport(BaseModel):
    valid: bool
    error_count: int
    warning_count: int
    issues: list[ValidationIssue]
    feedback_text: str
