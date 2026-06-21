"""校验即工具：把 command/structural 校验结果归一成 ValidationReport 作为 Observation。

调用形式（以源文件为准）：
  - command_validator: 模块级单例 CommandValidator()，调用 command_validator.validate(commands, edition)
    返回 list[dict]，每项 {command, valid, errors:[{type,message,suggestion}], warnings:[{message}]}
  - structural_validator: 模块级单例 StructuralValidator()，调用 structural_validator.validate(commands)
    返回 list[ValidationResult]；每个 ValidationResult 有 .command/.valid/.errors/.warnings
    ValidationError dataclass 有 .type/.message/.suggestion；warnings 是 list[str]
    format_feedback(results: list[ValidationResult]) -> str
"""

from __future__ import annotations

from typing import Any

from backend.agentloop.schemas import Observation, ValidationIssue, ValidationReport
from backend.agentloop.tools.registry import ToolContext, ToolRegistry
from backend.skills.command_validator import command_validator
from backend.skills.structural_validator import structural_validator

VALIDATE_COMMAND_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "validate_command",
        "description": "校验一条或多条 Minecraft 命令的语法、ID 合法性与结构正确性。在输出最终命令前调用以自检并据错误修正。",
        "parameters": {
            "type": "object",
            "properties": {
                "commands": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "待校验的命令列表（含或不含 / 前缀均可）",
                },
            },
            "required": ["commands"],
        },
    },
}


def make_validation_report(
    cmd_results: list[dict],
    struct_results: list,
    struct_feedback: str,
) -> ValidationReport:
    issues: list[ValidationIssue] = []

    # command_validator results: errors keys = {type, message, suggestion}; warnings keys = {message}
    for r in cmd_results:
        cmd = r.get("command", "")
        for err in r.get("errors", []) or []:
            issues.append(ValidationIssue(
                command=cmd,
                type=str(err.get("type", "syntax")),
                message=str(err.get("message", "")),
                suggestion=str(err.get("suggestion", "") or ""),
                severity="error",
            ))
        for warn in r.get("warnings", []) or []:
            issues.append(ValidationIssue(
                command=cmd,
                type="warning",
                message=str(warn.get("message", "")),
                suggestion="",
                severity="warning",
            ))

    # structural_validator results: ValidationResult dataclass
    # .command: str, .errors: list[ValidationError], .warnings: list[str]
    # ValidationError: .type, .message, .suggestion
    issues.extend(_structural_issues(struct_results))

    error_count = sum(1 for i in issues if i.severity == "error")
    warning_count = sum(1 for i in issues if i.severity == "warning")
    if error_count == 0:
        feedback_text = "✅ 校验通过，未发现问题。"
    else:
        feedback_text = struct_feedback or f"❌ {error_count} 个错误"
    return ValidationReport(
        valid=error_count == 0,
        error_count=error_count,
        warning_count=warning_count,
        issues=issues,
        feedback_text=feedback_text,
    )


def _structural_issues(struct_results: list) -> list[ValidationIssue]:
    """把 structural_validator 的 ValidationResult 列表转成 ValidationIssue。

    ValidationResult 字段（dataclass，源自 structural_validator.py）:
      .command: str
      .errors: list[ValidationError]  — ValidationError 有 .type / .message / .suggestion
      .warnings: list[str]            — 字符串列表（非 dict）
    """
    out: list[ValidationIssue] = []
    for res in struct_results or []:
        command = res.command
        for err in res.errors:
            out.append(ValidationIssue(
                command=command,
                type="structural_" + err.type,
                message=err.message,
                suggestion=err.suggestion or "",
                severity="error",
            ))
        for warn_str in res.warnings:
            out.append(ValidationIssue(
                command=command,
                type="structural_warning",
                message=str(warn_str),
                suggestion="",
                severity="warning",
            ))
    return out


async def handle_validate_command(args: dict, ctx: ToolContext) -> Observation:
    commands = args.get("commands")
    if commands is None and args.get("command"):
        commands = [args["command"]]
    if not commands:
        return Observation(tool_name="validate_command", ok=False, summary="请提供待校验的命令。")
    if isinstance(commands, str):
        commands = [commands]

    cmd_results = command_validator.validate(commands, ctx.edition)
    struct_results = structural_validator.validate(commands)
    struct_feedback = structural_validator.format_feedback(struct_results)

    report = make_validation_report(cmd_results, struct_results, struct_feedback)
    return Observation(
        tool_name="validate_command",
        ok=report.valid,
        summary=report.feedback_text,
        data=report.model_dump(),
    )


def register_validate_tool(reg: ToolRegistry) -> None:
    reg.register(VALIDATE_COMMAND_SCHEMA, handle_validate_command)
