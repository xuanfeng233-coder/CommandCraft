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
    # struct_feedback="" with errors → fallback to "❌ N 个错误"
    assert report.feedback_text == "❌ 1 个错误"


def test_make_report_valid_when_no_errors():
    # Even when struct_feedback contains a "请修正" header, valid case returns clean text
    struct_header = "## 命令校验发现以下问题，请修正后重新生成："
    cmd_results = [{"command": "/say hi", "valid": True, "errors": [], "warnings": []}]
    report = make_validation_report(cmd_results, struct_results=[], struct_feedback=struct_header)
    assert report.valid is True
    assert report.error_count == 0
    assert report.feedback_text == "✅ 校验通过，未发现问题。"


def test_make_report_errors_preserve_struct_feedback():
    # When errors exist, struct_feedback (the validator's text) is preserved verbatim
    struct_feedback = "## 命令校验发现以下问题，请修正后重新生成：\n- 错误1"
    cmd_results = [
        {"command": "/give @p bad_item", "valid": False,
         "errors": [{"type": "id", "message": "未知物品 bad_item", "suggestion": "diamond"}],
         "warnings": []},
    ]
    report = make_validation_report(cmd_results, struct_results=[], struct_feedback=struct_feedback)
    assert report.valid is False
    assert report.error_count == 1
    assert report.feedback_text == struct_feedback


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
