"""ReaderAgent — Pure regex-based PROJECT.md parser (no LLM).

Understands the structured markdown format:
  ## 步骤 N: {title} [x] / [ ] / [>]
  **需求**: ...
  **子任务**:
  - [x] done
  - [ ] pending
  - [>] in progress
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class SubTask:
    description: str = ""
    done: bool = False


@dataclass
class PlanStep:
    index: int = 0
    title: str = ""
    status: str = "pending"  # "pending" | "done" | "in_progress"
    raw_content: str = ""
    requirement: str = ""
    approach: str = ""
    commands: list[str] = field(default_factory=list)
    subtasks: list[SubTask] = field(default_factory=list)
    result_summary: str = ""


# Pattern for step headers: ## 步骤 N: Title [status]
_STEP_PATTERN = re.compile(
    r"^##\s+步骤\s*(\d+)\s*[:：]\s*(.+?)\s*\[([ x>])\]\s*$",
    re.MULTILINE,
)

# Pattern for subtask items
_SUBTASK_PATTERN = re.compile(r"^-\s*\[([ x>])\]\s*(.+)$", re.MULTILINE)

# Pattern for **field**: value
_FIELD_PATTERN = re.compile(r"\*\*(.+?)\*\*\s*[:：]\s*(.+?)(?=\n\*\*|\n##|\n$|\Z)", re.DOTALL)


class ReaderAgent:
    """Pure parser for PROJECT.md — no LLM calls."""

    def parse_plan(self, md_content: str) -> list[PlanStep]:
        """Parse the entire PROJECT.md into a list of PlanStep objects."""
        if not md_content.strip():
            return []

        steps: list[PlanStep] = []
        matches = list(_STEP_PATTERN.finditer(md_content))

        for i, match in enumerate(matches):
            step_num = int(match.group(1))
            title = match.group(2).strip()
            status_char = match.group(3)

            status = {"x": "done", ">": "in_progress", " ": "pending"}.get(
                status_char, "pending"
            )

            # Extract content between this step header and the next
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(md_content)
            raw_content = md_content[start:end].strip()

            step = PlanStep(
                index=step_num,
                title=title,
                status=status,
                raw_content=raw_content,
            )

            # Extract fields
            for field_match in _FIELD_PATTERN.finditer(raw_content):
                field_name = field_match.group(1).strip()
                field_value = field_match.group(2).strip()

                if field_name in ("需求", "需求描述"):
                    step.requirement = field_value
                elif field_name in ("实现思路", "方案"):
                    step.approach = field_value
                elif field_name in ("涉及命令", "命令"):
                    step.commands = [
                        c.strip() for c in field_value.split(",") if c.strip()
                    ]
                elif field_name in ("结果摘要", "执行结果"):
                    step.result_summary = field_value

            # Extract subtasks
            for sub_match in _SUBTASK_PATTERN.finditer(raw_content):
                sub_status = sub_match.group(1)
                sub_desc = sub_match.group(2).strip()
                step.subtasks.append(SubTask(
                    description=sub_desc,
                    done=sub_status == "x",
                ))

            steps.append(step)

        return steps

    def get_step(self, md_content: str, step_index: int) -> PlanStep | None:
        """Get a specific step by its index number."""
        steps = self.parse_plan(md_content)
        for step in steps:
            if step.index == step_index:
                return step
        return None

    def get_current_step(self, md_content: str) -> PlanStep | None:
        """Get the first uncompleted step."""
        steps = self.parse_plan(md_content)
        for step in steps:
            if step.status != "done":
                return step
        return None

    def count_steps(self, md_content: str) -> tuple[int, int]:
        """Return (completed_count, total_count)."""
        steps = self.parse_plan(md_content)
        completed = sum(1 for s in steps if s.status == "done")
        return completed, len(steps)

    def get_overview(self, md_content: str) -> str:
        """Extract the overview section (before the first step)."""
        match = _STEP_PATTERN.search(md_content)
        if match:
            overview = md_content[:match.start()].strip()
        else:
            overview = md_content.strip()

        # Remove the top-level title
        lines = overview.split("\n")
        result_lines: list[str] = []
        for line in lines:
            if line.startswith("# ") and not result_lines:
                continue  # Skip project title
            if line.startswith("## 概述"):
                continue  # Skip overview header
            result_lines.append(line)

        return "\n".join(result_lines).strip()


# Singleton
reader_agent = ReaderAgent()
