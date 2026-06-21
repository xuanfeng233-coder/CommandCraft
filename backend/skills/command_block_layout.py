"""Skill 8: CommandBlockLayout — Generates 3D command block layout from project tasks."""

from __future__ import annotations

from typing import Any

from backend.skills.base import BaseSkill

# Block type mapping
_BLOCK_TYPE_MAP = {
    "impulse": "command_block",
    "chain": "chain_command_block",
    "repeating": "repeating_command_block",
}


class CommandBlockLayout(BaseSkill):
    """Rule-based command block layout generator (no LLM needed)."""

    name = "CommandBlockLayout"
    description = "根据项目任务列表生成三维命令方块布局"

    def build_system_prompt(self, context: dict[str, Any]) -> str:
        # This skill is rule-based, not LLM-based
        return ""

    def parse_output(self, raw: str) -> dict[str, Any]:
        # Not used — this skill works via generate_layout()
        return {}

    def generate_layout(self, project_data: dict[str, Any]) -> dict[str, Any]:
        """Generate layout from ProjectPlanner output.

        Arranges command block chains along the X axis, each task group
        offset on the Z axis.  Within a chain, blocks extend along +X
        (east-facing).
        """
        phases = project_data.get("phases", [])

        layout: list[dict[str, Any]] = []
        groups: list[dict[str, Any]] = []

        z_offset = 0  # Each task group gets its own Z row
        max_x = 0

        for phase in phases:
            for task in phase.get("tasks", []):
                task_id = task.get("task_id", "")
                blocks = task.get("command_blocks", [])
                if not blocks:
                    continue

                group_id = f"group_{task_id}"
                groups.append({
                    "group_id": group_id,
                    "name": task.get("description", f"Task {task_id}")[:40],
                    "description": task.get("description", ""),
                    "trigger_method": self._infer_trigger(blocks),
                })

                for x_idx, block in enumerate(blocks):
                    block_type_raw = block.get("type", "chain")
                    layout.append({
                        "position": {"x": x_idx, "y": 0, "z": z_offset},
                        "direction": "east",
                        "block_type": _BLOCK_TYPE_MAP.get(block_type_raw, "chain_command_block"),
                        "conditional": block.get("conditional", False),
                        "auto": not block.get("needs_redstone", False),
                        "command": block.get("command", ""),
                        "custom_name": block.get("comment", ""),
                        "group_id": group_id,
                    })
                    if x_idx + 1 > max_x:
                        max_x = x_idx + 1

                z_offset += 2  # Leave 1-block gap between rows

        dimensions = {
            "width": max_x,
            "height": 1,
            "depth": max(z_offset, 1),
        }

        return {
            "layout": layout,
            "groups": groups,
            "dimensions": dimensions,
        }

    def generate_vertical_layout(self, project_data: dict[str, Any]) -> dict[str, Any]:
        """Generate a vertical column layout (Y-axis stacking).

        Each command chain occupies one column along the X axis.
        Within a column, blocks stack upward along Y.
        Columns are spaced 2 blocks apart on X.

        Layout:
          Column 0 (x=0):  [起点] → [链] → [链]     (y=0, 1, 2)
          Column 1 (x=2):  [起点] → [链] → [链] → [链]  (y=0, 1, 2, 3)
        """
        phases = project_data.get("phases", [])

        layout: list[dict[str, Any]] = []
        groups: list[dict[str, Any]] = []

        x_offset = 0
        max_y = 0

        for phase in phases:
            for task in phase.get("tasks", []):
                task_id = task.get("task_id", "")
                blocks = task.get("command_blocks", [])
                if not blocks:
                    continue

                group_id = f"group_{task_id}"
                groups.append({
                    "group_id": group_id,
                    "name": task.get("description", f"Task {task_id}")[:40],
                    "description": task.get("description", ""),
                    "trigger_method": self._infer_trigger(blocks),
                })

                for y_idx, block in enumerate(blocks):
                    block_type_raw = block.get("type", "chain")
                    layout.append({
                        "position": {"x": x_offset, "y": y_idx, "z": 0},
                        "direction": "up",
                        "block_type": _BLOCK_TYPE_MAP.get(block_type_raw, "chain_command_block"),
                        "conditional": block.get("conditional", False),
                        "auto": not block.get("needs_redstone", False),
                        "command": block.get("command", ""),
                        "custom_name": block.get("comment", ""),
                        "group_id": group_id,
                    })
                    if y_idx + 1 > max_y:
                        max_y = y_idx + 1

                x_offset += 2  # 1-block gap between columns

        dimensions = {
            "width": max(x_offset, 1),
            "height": max(max_y, 1),
            "depth": 1,
        }

        return {
            "layout": layout,
            "groups": groups,
            "dimensions": dimensions,
        }

    @staticmethod
    def _infer_trigger(blocks: list[dict]) -> str:
        """Infer the trigger method from the first block type."""
        if not blocks:
            return ""
        first_type = blocks[0].get("type", "")
        if first_type == "repeating":
            return "循环执行（始终活动）"
        elif first_type == "impulse":
            return "红石信号触发（一次性）"
        return "连锁执行"


command_block_layout = CommandBlockLayout()
