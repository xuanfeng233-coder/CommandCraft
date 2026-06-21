"""finish 终止工具 + 默认注册表装配。

finish 是终止动作：循环检测到 name=='finish' 时据其 reason 终止；本 handler 只归一参数。
"""

from __future__ import annotations

from typing import Any

from backend.agentloop.schemas import Observation
from backend.agentloop.tools.lookup import register_lookup_tools
from backend.agentloop.tools.registry import ToolContext, ToolRegistry
from backend.agentloop.tools.search import register_search_tools
from backend.agentloop.tools.validate import register_validate_tool

_VALID_REASONS = {"done", "ask_user", "give_up"}

FINISH_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "finish",
        "description": "结束任务并给出最终结果。done=已生成命令；ask_user=需要用户澄清；give_up=无法完成。",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "enum": ["done", "ask_user", "give_up"]},
                "final_answer": {
                    "type": "string",
                    "description": "最终输出。done 时为符合输出规范的结果；ask_user 时为追问文本。",
                },
            },
            "required": ["reason", "final_answer"],
        },
    },
}


async def handle_finish(args: dict, ctx: ToolContext) -> Observation:
    reason = str(args.get("reason", "")).strip()
    if reason not in _VALID_REASONS:
        reason = "give_up"
    final_answer = str(args.get("final_answer", ""))
    return Observation(
        tool_name="finish", ok=True,
        summary=f"finish: {reason}",
        data={"reason": reason, "final_answer": final_answer},
    )


def register_finish_tool(reg: ToolRegistry) -> None:
    reg.register(FINISH_SCHEMA, handle_finish)


def build_default_registry() -> ToolRegistry:
    """装配 7 个工具的默认注册表（每个 AgentLoop 构造时调用一次，廉价）。"""
    reg = ToolRegistry()
    register_lookup_tools(reg)     # 4 个本地查询
    register_validate_tool(reg)    # validate_command
    register_search_tools(reg)     # search_web
    register_finish_tool(reg)      # finish
    return reg
