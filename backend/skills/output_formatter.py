"""Skill 10: OutputFormatter — Normalizes Agent 2 output to frontend-ready structure."""

from __future__ import annotations

from typing import Any

from backend.skills.base import BaseSkill


class OutputFormatter(BaseSkill):
    """Rule-based output normalizer (no LLM needed).

    Ensures all output follows the expected schema before sending to frontend.
    """

    name = "OutputFormatter"
    description = "统一格式化输出为前端可渲染的 JSON 结构"

    def build_system_prompt(self, context: dict[str, Any]) -> str:
        # Rule-based, no system prompt needed
        return ""

    def parse_output(self, raw: str) -> dict[str, Any]:
        # Not used directly
        return {}

    def format_result(self, result_data: dict[str, Any]) -> dict[str, Any]:
        """Normalize a result dict to ensure all required fields exist."""
        result_type = result_data.get("type", "single_command")

        if result_type == "single_command":
            return self._format_command(result_data)
        elif result_type == "conversation":
            return self._format_conversation(result_data)
        elif result_type == "project":
            return self._format_project(result_data)
        else:
            return self._format_command(result_data)

    def _format_command(self, data: dict[str, Any]) -> dict[str, Any]:
        cmd = data.get("command", {})

        # Fallback: if "command" is empty but "commands" array exists, merge it
        if not cmd and isinstance(data.get("commands"), list):
            cmd_strs = []
            for item in data["commands"]:
                if isinstance(item, str):
                    cmd_strs.append(item)
                elif isinstance(item, dict) and "command" in item:
                    cmd_strs.append(item["command"])
            cmd = {
                "command": "\n".join(cmd_strs),
                "explanation": data.get("explanation", ""),
                "variants": data.get("variants", []),
                "warnings": data.get("warnings", []),
            }

        if isinstance(cmd, str):
            cmd = {"command": cmd, "explanation": "", "variants": [], "warnings": []}
        elif isinstance(cmd, dict):
            cmd.setdefault("command", "")
            cmd.setdefault("explanation", "")
            cmd.setdefault("variants", [])
            cmd.setdefault("warnings", [])

        # Pass through template field if present
        template = data.get("template")
        if template and isinstance(cmd, dict):
            cmd["template"] = template

        return {
            "type": "single_command",
            "command": cmd,
            "questions": None,
            "project": None,
            "message": data.get("message"),
            "thinking": data.get("thinking"),
        }

    def _format_conversation(self, data: dict[str, Any]) -> dict[str, Any]:
        questions = data.get("questions", [])
        for q in questions:
            q.setdefault("param", "")
            q.setdefault("question", "")
            q.setdefault("options", [])
            q.setdefault("default", None)

        result: dict[str, Any] = {
            "type": "conversation",
            "command": None,
            "questions": questions,
            "project": None,
            "message": data.get("current_progress", data.get("message", "")),
            "thinking": data.get("thinking"),
        }

        # Pass through template metadata from template fast path
        template = data.get("template")
        if template:
            result["template"] = template

        return result

    def _format_project(self, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "project",
            "command": None,
            "questions": None,
            "project": {
                "project_name": data.get("project_name", ""),
                "overview": data.get("overview", ""),
                "phases": data.get("phases", []),
                "layout": data.get("layout", []),
                "groups": data.get("groups", []),
                "dimensions": data.get("dimensions", {"width": 0, "height": 0, "depth": 0}),
            },
            "message": data.get("overview", ""),
            "thinking": data.get("thinking"),
        }


output_formatter = OutputFormatter()
