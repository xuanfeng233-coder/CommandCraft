"""task_result.py — typed 前驱上下文 TaskResult + 渲染 + legacy 适配器

Replaces the string-concat predecessor injection in
backend/orchestrator/orchestrator.py _inject_predecessor_context (lines ~243-300)
with a typed dataclass + pure render function that produces byte-identical output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class TaskResult:
    task_id: str
    description: str
    result_type: Literal["single_command", "project", "conversation"]
    commands: list[str]
    explanation: str = ""
    user_answer: str = ""


def render_predecessor_block(deps: list[TaskResult]) -> str:
    """Render a list of TaskResult into the predecessor context text.

    Produces text byte-identical to orchestrator._inject_predecessor_context
    (lines ~243-300 of backend/orchestrator/orchestrator.py).

    The legacy method joins context_parts with "\\n" and prepends a
    "## 前置任务结果\\n" header when attaching to user_request.
    This function returns the joined context_parts text (without the header);
    the header is added by build_single_task_messages, mirroring the legacy.
    """
    context_parts: list[str] = []

    for tr in deps:
        dep_id = tr.task_id
        dep_desc = tr.description

        # Inject user answer from resumed predecessor (if any) — legacy lines ~269-272
        if tr.user_answer:
            context_parts.append(
                f"用户在前置任务 {dep_id}（{dep_desc}）中的回答：{tr.user_answer}"
            )

        if tr.result_type == "single_command":
            # legacy lines ~278-282
            cmd_str = tr.commands[0] if tr.commands else ""
            context_parts.append(
                f"前置任务 {dep_id}（{dep_desc}）已生成命令：{cmd_str}"
            )
            if tr.explanation:
                context_parts.append(f"说明：{tr.explanation}")
        elif tr.result_type == "project":
            # legacy lines ~283-294: join all commands with "; "
            context_parts.append(
                f"前置任务 {dep_id}（{dep_desc}）已生成命令：{'; '.join(tr.commands)}"
            )
        # "conversation" type: only user_answer is injected (above); no commands line

    return "\n".join(context_parts)


def task_result_from_legacy(
    dep_id: str,
    completed: dict[str, Any],
    user_answer: str = "",
) -> TaskResult:
    """Build a TaskResult from the legacy _completed_results[dep] dict shape.

    Supports both "single_command" and "project" result types, flattening
    commands in the same order as _inject_predecessor_context.
    """
    result_type = completed.get("type", "")
    commands: list[str] = []
    explanation: str = ""

    if result_type == "single_command":
        cmd_obj = completed.get("command", {})
        if isinstance(cmd_obj, dict):
            cmd_str = cmd_obj.get("command", "")
            explanation = cmd_obj.get("explanation", "")
        else:
            cmd_str = ""
        if cmd_str:
            commands = [cmd_str]
    elif result_type == "project":
        # legacy lines ~285-291: phase → task → command_blocks expansion order
        for phase in completed.get("phases", []):
            for task in phase.get("tasks", []):
                for block in task.get("command_blocks", []):
                    c = block.get("command", "")
                    if c:
                        commands.append(c)

    # Normalise result_type to the Literal union; fall back to "conversation"
    typed_result_type: Literal["single_command", "project", "conversation"]
    if result_type == "single_command":
        typed_result_type = "single_command"
    elif result_type == "project":
        typed_result_type = "project"
    else:
        typed_result_type = "conversation"

    return TaskResult(
        task_id=dep_id,
        description="",  # caller should fill in from task list
        result_type=typed_result_type,
        commands=commands,
        explanation=explanation,
        user_answer=user_answer,
    )
