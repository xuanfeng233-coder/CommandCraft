import json

from backend.agentloop.schemas import (
    AgentOutcome,
    FinishReason,
    LoopBudget,
    Observation,
    StepResult,
    ToolCall,
    ValidationIssue,
    ValidationReport,
)


def test_observation_to_tool_content_is_str_summary_only():
    obs = Observation(tool_name="x", ok=True, summary="结果文本")
    content = obs.to_tool_content()
    assert isinstance(content, str)
    assert "结果文本" in content


def test_observation_to_tool_content_includes_data_json():
    obs = Observation(tool_name="x", ok=True, summary="摘要", data={"k": 1})
    content = obs.to_tool_content()
    assert isinstance(content, str)
    assert "摘要" in content
    # data 以 JSON 形式附带，模型可解析
    assert '"k"' in content and "1" in content


def test_observation_error_serializes():
    obs = Observation(tool_name="x", ok=False, summary="失败", error="boom")
    content = obs.to_tool_content()
    assert isinstance(content, str)
    assert "boom" in content


def test_loop_budget_defaults_and_warning():
    b = LoopBudget()
    assert b.max_rounds == 8
    assert b.warn_at_round == 7
    assert b.max_search_web_calls == 2
    w = b.warning_text(7)
    assert isinstance(w, str) and ("7" in w or "finish" in w)


def test_finish_reason_is_str_enum():
    assert FinishReason.DONE == "done"
    assert FinishReason("ask_user") is FinishReason.ASK_USER


def test_step_result_and_toolcall():
    sr = StepResult(content="hi", thinking="", tool_calls=[ToolCall("id1", "finish", {"reason": "done"})], raw_assistant_msg={"role": "assistant", "content": "hi"})
    assert sr.tool_calls[0].name == "finish"
    assert sr.raw_assistant_msg["role"] == "assistant"


def test_agent_outcome_holds_trace():
    out = AgentOutcome(reason=FinishReason.DONE, content="c", thinking="t", observations=[], rounds_used=2)
    assert out.reason is FinishReason.DONE
    assert out.rounds_used == 2


def test_validation_report_roundtrip():
    rep = ValidationReport(
        valid=False, error_count=1, warning_count=0,
        issues=[ValidationIssue(command="/give @p x", type="id", message="未知物品", severity="error")],
        feedback_text="❌ 1 个错误",
    )
    dumped = rep.model_dump()
    assert dumped["valid"] is False
    assert dumped["issues"][0]["severity"] == "error"
    # 可被 json 序列化（进 Observation.data）
    json.dumps(dumped, ensure_ascii=False)
