"""single_task.py — 单任务共享逻辑（唯一实现）

提供三个纯函数，供 TaskAgent 委托调用，也供其他模块（agentloop 循环等）直接调用：
- build_single_task_messages  — 组装 system+user 消息列表
- parse_output                — 解析 LLM 原始输出为结构化 dict
- run_validation              — 原地调用 CommandValidator 并写回结果

常量 (_BASE_TEMPLATE* / _TYPE_SECTIONS*) 留在 backend.agents.task_agent，
此模块从那里 import——避免循环（task_agent 不导入 single_task 常量）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from backend.skills.base import BaseSkill
from backend.skills.command_validator import command_validator

if TYPE_CHECKING:
    from backend.agents.task_result import TaskResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# build_single_task_messages
# ---------------------------------------------------------------------------

def build_single_task_messages(
    user_request: str,
    output_type: str,
    command_directory: str,
    *,
    edition: str = "bedrock",
    ambiguous: bool = False,
    predecessors: "list[TaskResult] | None" = None,
) -> list[dict[str, Any]]:
    """Assemble the system + user message list for a single-task LLM call.

    Moved verbatim from TaskAgent.execute (lines ~949-959) and TaskAgent._build_prompt
    (lines ~1071-1083).  TaskAgent delegates to this function.
    """
    # Import constants from task_agent to avoid duplication / circular import.
    # task_agent defines the constants at module level; it does NOT import single_task,
    # so there is no circular dependency.
    from backend.agents.task_agent import (
        _BASE_TEMPLATE,
        _BASE_TEMPLATE_JAVA,
        _SIMPLE_COMMAND_SECTION,
        _SIMPLE_COMMAND_SECTION_JAVA,
        _TYPE_SECTIONS,
        _TYPE_SECTIONS_JAVA,
    )

    ambiguity_hint = ""
    if ambiguous:
        ambiguity_hint = "\n\n## 歧义提示\n此需求存在歧义，请优先输出 conversation 类型进行追问。"

    # Build system prompt (mirrors _build_prompt)
    full_directory = command_directory + ambiguity_hint
    if edition == "java":
        type_section = _TYPE_SECTIONS_JAVA.get(output_type, _SIMPLE_COMMAND_SECTION_JAVA)
        system_prompt = _BASE_TEMPLATE_JAVA.format(
            type_specific_section=type_section,
            command_directory=full_directory,
        )
    else:
        type_section = _TYPE_SECTIONS.get(output_type, _SIMPLE_COMMAND_SECTION)
        system_prompt = _BASE_TEMPLATE.format(
            type_specific_section=type_section,
            command_directory=full_directory,
        )

    # Append predecessor context when provided (mirrors orchestrator lines ~296-299)
    effective_user_request = user_request
    if predecessors is not None:
        from backend.agents.task_result import render_predecessor_block
        predecessor_text = render_predecessor_block(predecessors)
        if predecessor_text:
            effective_user_request = (
                f"{user_request}\n\n## 前置任务结果\n{predecessor_text}"
            )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": effective_user_request},
    ]


# ---------------------------------------------------------------------------
# parse_output
# ---------------------------------------------------------------------------

def parse_output(raw: str, output_type: str) -> dict[str, Any]:
    """Parse raw LLM output into structured data.

    Moved verbatim from TaskAgent._parse_output (lines ~1085-1124),
    TaskAgent._looks_like_conversation (lines ~1126-1148), and
    TaskAgent._normalize_output (lines ~1150-1195).
    """
    data = BaseSkill.extract_json(raw)

    if isinstance(data, dict) and "type" in data:
        return _normalize_output(data)

    # JSON extraction failed — detect if this is a conversational response
    if raw and _looks_like_conversation(raw):
        logger.info("_parse_output: JSON failed but detected conversational text, wrapping as conversation type")
        return {
            "type": "conversation",
            "questions": [
                {
                    "param": "user_clarification",
                    "question": raw.strip(),
                    "options": [],
                    "default": None,
                }
            ],
            "current_progress": "",
        }

    if output_type == "project":
        return {
            "type": "project",
            "project_name": "解析失败",
            "overview": raw[:500] if raw else "",
            "phases": [],
        }
    else:
        return {
            "type": "single_command",
            "command": {
                "command": "",
                "explanation": raw[:500] if raw else "",
                "variants": [],
                "warnings": ["JSON 解析失败，请查看原始输出"],
            },
        }


def _looks_like_conversation(text: str) -> bool:
    """Heuristic: detect if raw text is a parameter refinement question.

    Moved verbatim from TaskAgent._looks_like_conversation (lines ~1126-1148).
    Chinese keyword lists preserved exactly.
    """
    has_question = "？" in text or "?" in text
    strong_keywords = ("请提供", "请指定", "请选择", "请确认", "请告诉",
                       "需要您", "需要你", "以下信息")
    has_strong_keyword = any(kw in text for kw in strong_keywords)
    weak_keywords = ("哪种", "哪个", "什么类型", "什么物品", "什么方块", "什么实体")
    has_weak_keyword = any(kw in text for kw in weak_keywords)
    has_numbered_list = any(f"{i}." in text or f"{i}、" in text or f"{i}. " in text
                            for i in range(1, 6))
    text_stripped = text.strip()
    starts_with_command = text_stripped.startswith("/")

    if starts_with_command:
        return False
    if has_strong_keyword:
        return True
    if has_weak_keyword and has_question:
        return True
    if has_question and has_numbered_list:
        return True
    return False


def _normalize_output(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize execute_chain/selector/rawtext types to single_command.

    Moved verbatim from TaskAgent._normalize_output (lines ~1150-1195).
    """
    result_type = data.get("type", "")

    if result_type in ("execute_chain", "selector", "rawtext"):
        cmd_obj = data.get("command")
        commands_arr = data.get("commands")

        if cmd_obj is None and isinstance(commands_arr, list):
            cmd_strs = []
            for item in commands_arr:
                if isinstance(item, str):
                    cmd_strs.append(item)
                elif isinstance(item, dict) and "command" in item:
                    cmd_strs.append(item["command"])
            merged_cmd = "\n".join(cmd_strs) if cmd_strs else ""
            cmd_obj = {
                "command": merged_cmd,
                "explanation": data.get("explanation", ""),
                "variants": data.get("variants", []),
                "warnings": data.get("warnings", []),
            }
        elif isinstance(cmd_obj, str):
            cmd_obj = {
                "command": cmd_obj,
                "explanation": data.get("explanation", ""),
                "variants": data.get("variants", []),
                "warnings": data.get("warnings", []),
            }

        if isinstance(cmd_obj, dict):
            for key in ("chain_breakdown", "selector_breakdown", "preview"):
                if key in data and key not in cmd_obj:
                    cmd_obj[key] = data[key]

        data["type"] = "single_command"
        data["command"] = cmd_obj or {
            "command": "",
            "explanation": "",
            "variants": [],
            "warnings": [],
        }
        data.pop("commands", None)

    return data


# ---------------------------------------------------------------------------
# run_validation
# ---------------------------------------------------------------------------

def run_validation(content_data: dict[str, Any]) -> None:
    """Run CommandValidator and merge results into content_data in-place.

    Moved verbatim from TaskAgent._run_validation (lines ~1197-1240).

    NOTE: command_validator.validate(cmd_lines) is called WITHOUT an edition
    argument — this matches the legacy call at line ~1210 of task_agent.py.
    Do NOT add edition here for parity.  The agentloop's own validate_command
    tool (Phase 2A, backend/agentloop/tools/) is the edition-correct path for
    future callers.
    """
    command_obj = content_data.get("command")
    if not command_obj or not isinstance(command_obj, dict):
        return
    cmd_str = command_obj.get("command", "")
    if not cmd_str:
        return

    cmd_lines = [line.strip() for line in cmd_str.split("\n") if line.strip()]

    try:
        results = command_validator.validate(cmd_lines)
        if not results:
            return

        all_errors = []
        all_warnings = []
        all_valid = True

        for validation in results:
            errors = validation.get("errors", [])
            warnings_list = [w["message"] for w in validation.get("warnings", [])]
            if errors:
                all_valid = False
                for err in errors:
                    all_errors.append(
                        f"[{err['type']}] {err['message']} — {err.get('suggestion', '')}"
                    )
            all_warnings.extend(warnings_list)

        existing = command_obj.get("warnings") or []
        existing.extend(all_errors)
        existing.extend(all_warnings)
        if existing:
            command_obj["warnings"] = existing

        command_obj["validation"] = {
            "valid": all_valid,
            "error_count": len(all_errors),
        }
    except Exception as e:
        logger.warning("CommandValidator failed: %s", e)
