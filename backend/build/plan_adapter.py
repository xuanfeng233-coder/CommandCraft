"""plan_adapter — Convert a Planner Decomposition into PROJECT.md markdown.

The rendered markdown is designed to round-trip through
``backend.build.agents.reader_agent.parse_plan`` without loss of step count,
order, titles, or status.

Key contracts (derived from reader_agent regexes):
- Step header:  ``## 步骤 N: <title> [ ]``
  (_STEP_PATTERN — status char must be exactly one space inside brackets)
- Field lines:  ``**需求**: …``, ``**实现思路**: …``, ``**涉及命令**: …``
  (_FIELD_PATTERN lookahead stops at the next ``\\n**`` or ``\\n##``)
- At least one subtask ``- [ ] …`` so subtasks list is non-empty.
- Sanitize: strip ``[``, ``]``, ``**``, and trailing whitespace from any
  text that lands in the step header or field values — these chars silently
  break _STEP_PATTERN / _FIELD_PATTERN.
"""

from __future__ import annotations

import re

from backend.agents.planner_schemas import Decomposition

# Characters that break the reader_agent regexes when they appear in the
# step header title or inside field values.
# 去掉 [、]、*（单个 * 的移除同时消除 ** markdown 粗体）
_STRIP_RE = re.compile(r"[\[\]*]")


def _sanitize(text: str) -> str:
    """Remove ``[``, ``]``, ``*`` characters and strip trailing whitespace."""
    cleaned = _STRIP_RE.sub("", text)
    return cleaned.strip()


def decomposition_to_project_md(d: Decomposition, user_request: str) -> str:  # noqa: ARG001
    """Render a Decomposition as a PROJECT.md string.

    The output is parseable by ``reader_agent.parse_plan`` and produces the
    same number of steps in the same order, all with ``status == "pending"``.

    Args:
        d: The Decomposition produced by the Planner.
        user_request: The original user request (carried for context; not
            directly rendered but available for future extension).

    Returns:
        A markdown string in PROJECT.md format.
    """
    lines: list[str] = []

    # Top-level title (get_overview skips this line)
    lines.append(f"# {d.project_name}")
    lines.append("")

    # Overview section (get_overview returns everything before first ## 步骤)
    if d.overview:
        lines.append(d.overview)
        lines.append("")

    for i, task in enumerate(d.tasks, start=1):
        safe_title = _sanitize(task.title or task.instruction or f"任务{i}")
        safe_instruction = _sanitize(task.instruction or task.title or "")
        commands_str = ", ".join(task.recommended_commands) if task.recommended_commands else "无"

        # Step header — status char is exactly a single space → "pending"
        lines.append(f"## 步骤 {i}: {safe_title} [ ]")

        # Field lines — reader_agent matches **field**: value up to next \n** or \n##
        lines.append(f"**需求**: {safe_title}")
        lines.append(f"**实现思路**: {safe_instruction}")
        lines.append(f"**涉及命令**: {commands_str}")

        # Optional dependency note (plain text, not a parsed field)
        if task.depends_on:
            dep_labels = "、".join(f"步骤 {dep}" for dep in task.depends_on)
            lines.append(f"**依赖**: {dep_labels}")

        # At least one subtask so subtasks list is non-empty
        lines.append(f"- [ ] {safe_instruction or safe_title}")
        lines.append("")

    return "\n".join(lines)
