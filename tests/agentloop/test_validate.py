import pytest

from backend.agentloop.schemas import LoopBudget, ValidationReport
from backend.agentloop.tools.registry import ToolContext, ToolRegistry
from backend.agentloop.tools.validate import (
    make_validation_report,
    register_validate_tool,
)


def _ctx(edition="bedrock"):
    return ToolContext(edition=edition, budget=LoopBudget(), counters={})


def _reg():
    reg = ToolRegistry()
    register_validate_tool(reg)
    return reg


def test_make_report_merges_errors_and_warnings():
    cmd_results = [
        {"command": "/give @p bad_item", "valid": False,
         "errors": [{"type": "id", "message": "未知物品 bad_item", "suggestion": "diamond"}],
         "warnings": []},
        {"command": "/say hi", "valid": True, "errors": [], "warnings": [{"message": "可优化"}]},
    ]
    report = make_validation_report(cmd_results, struct_results=[], struct_feedback="")
    assert isinstance(report, ValidationReport)
    assert report.error_count == 1
    assert report.warning_count == 1
    assert report.valid is False
    sev = sorted(i.severity for i in report.issues)
    assert sev == ["error", "warning"]


def test_make_report_valid_when_no_errors():
    cmd_results = [{"command": "/say hi", "valid": True, "errors": [], "warnings": []}]
    report = make_validation_report(cmd_results, struct_results=[], struct_feedback="✅")
    assert report.valid is True
    assert report.error_count == 0
    assert report.feedback_text == "✅"


async def test_validate_tool_registers_and_runs():
    reg = _reg()
    assert "validate_command" in reg.names()
    obs = await reg.execute("validate_command", {"commands": ["/give @p diamond 1"]}, _ctx())
    assert isinstance(obs.to_tool_content(), str)
    assert "valid" in obs.data  # data 是 ValidationReport.model_dump()


async def test_validate_tool_accepts_single_command_string():
    reg = _reg()
    obs = await reg.execute("validate_command", {"command": "/give @p diamond 1"}, _ctx())
    assert obs.tool_name == "validate_command"
    assert "valid" in obs.data
