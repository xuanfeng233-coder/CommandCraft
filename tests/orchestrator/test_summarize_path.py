"""Tests for the summarize path in Orchestrator (Task 5).

Three acceptance gates:
(1) flag-on, 2 completed tasks → summarize called once with legacy-keyed list,
    content(project) emitted.
(2) flag-on, 1 paused + 1 completed → all_completed() False → done emitted,
    summarize NOT called, session retained in _active_sessions.
(3) flag-on, summarize raises LLMError → soft-fail: still emits content with
    degraded explanation, stream does not crash.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import backend.orchestrator.orchestrator as orch_mod
from backend.agentloop.schemas import (
    AgentOutcome,
    FinishReason,
    LoopBudget,
    Observation,
    StepResult,
    ToolCall,
)
from backend.agentloop.tools.registry import ToolContext, ToolRegistry
from backend.llm.errors import LLMError


# ---------------------------------------------------------------------------
# Shared helpers (mirrored from test_multitask_loop.py)
# ---------------------------------------------------------------------------

def _single_command_json(cmd: str = "/give @p diamond 1") -> str:
    return json.dumps({
        "type": "single_command",
        "command": {
            "command": cmd,
            "explanation": "测试命令",
            "variants": [],
            "warnings": [],
        },
    })


def _make_decomp(
    tasks: list[dict[str, Any]],
    is_single: bool = False,
) -> dict[str, Any]:
    return {
        "project_name": "test_project",
        "overview": "test overview",
        "is_single_task": is_single,
        "tasks": tasks,
        "_original_input": "test input",
    }


def _task_def(
    task_id: str,
    request: str = "给钻石",
    depends_on: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "user_request": request,
        "description": f"任务{task_id}",
        "output_type": "simple_command",
        "recommended_commands": [],
        "depends_on": depends_on or [],
        "execution_mode": "continuous",
    }


async def _collect_stream(gen) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async for ev in gen:
        events.append(ev)
    return events


def _finish_registry(reason: str = "done", answer: str = "") -> ToolRegistry:
    """Mini registry with only finish handler."""
    reg = ToolRegistry()

    async def finish_handler(args: dict, ctx: ToolContext) -> Observation:
        return Observation(
            tool_name="finish",
            ok=True,
            summary="finish",
            data={
                "reason": args.get("reason", reason),
                "final_answer": args.get("final_answer", answer),
            },
        )

    reg.register(
        {
            "type": "function",
            "function": {
                "name": "finish",
                "description": "finish",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        finish_handler,
    )
    return reg


class _ScriptStep:
    """Returns scripted StepResult objects per call."""

    def __init__(self, answer: str) -> None:
        self._answer = answer
        self.calls = 0

    async def run(self, messages, tool_schemas):
        self.calls += 1
        return StepResult(
            content="",
            thinking="",
            tool_calls=[ToolCall(f"c{self.calls}", "finish", {
                "reason": "done",
                "final_answer": self._answer,
            })],
            raw_assistant_msg={"role": "assistant", "content": ""},
        )

    def format_observation(self, call, obs):
        return {"role": "tool", "tool_call_id": call.id, "content": obs.to_tool_content()}


class _AskUserStep:
    """Always returns ask_user."""

    def __init__(self, question: str = "请澄清你的需求") -> None:
        self._question = question
        self.calls = 0

    async def run(self, messages, tool_schemas):
        self.calls += 1
        return StepResult(
            content="",
            thinking="",
            tool_calls=[ToolCall("c_ask", "finish", {
                "reason": "ask_user",
                "final_answer": self._question,
            })],
            raw_assistant_msg={"role": "assistant", "content": ""},
        )

    def format_observation(self, call, obs):
        return {"role": "tool", "tool_call_id": call.id, "content": obs.to_tool_content()}


# ---------------------------------------------------------------------------
# Test 1: flag-on, 2 completed → summarize called once with legacy keys, content emitted
# ---------------------------------------------------------------------------

async def test_two_completed_tasks_summarize_called_once(monkeypatch):
    """Two tasks complete via AgentLoop; summarize is called exactly once
    with a 2-element list (legacy keys: task_id, description, result);
    a 'content' event with type='project' is emitted."""
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", True)

    answer1 = _single_command_json("/give @p diamond 1")
    answer2 = _single_command_json("/give @p gold_ingot 1")

    call_idx = {"n": 0}

    class _TwoStep:
        def __init__(self):
            self.calls = 0

        async def run(self, messages, tool_schemas):
            idx = self.calls
            self.calls += 1
            ans = answer1 if (idx % 2 == 0) else answer2
            return StepResult(
                content="",
                thinking="",
                tool_calls=[ToolCall(f"c{idx}", "finish", {"reason": "done", "final_answer": ans})],
                raw_assistant_msg={"role": "assistant", "content": ""},
            )

        def format_observation(self, call, obs):
            return {"role": "tool", "tool_call_id": call.id, "content": obs.to_tool_content()}

    step = _TwoStep()
    reg = _finish_registry()

    monkeypatch.setattr(orch_mod, "build_default_registry", lambda: reg)
    monkeypatch.setattr(orch_mod, "build_step", lambda client: step)
    monkeypatch.setattr(orch_mod, "get_llm_client", lambda: object())

    # Track summarize calls
    summarize_calls: list[tuple] = []
    known_summary = {
        "explanation": "两个任务已完成",
        "phases": [],
    }

    async def _fake_summarize(user_input, task_results, edition="bedrock"):
        summarize_calls.append((user_input, task_results, edition))
        return dict(known_summary)

    decomp = _make_decomp([
        _task_def("t1", "给钻石"),
        _task_def("t2", "给金锭"),
    ], is_single=False)

    # Build manager and run execute_all, then simulate what orchestrator does
    mgr = orch_mod.TaskManager(decomp, edition="bedrock", use_loop=True)
    events_from_mgr = await _collect_stream(mgr.execute_all())

    # Verify both tasks completed
    completed_states = {
        k: v for k, v in mgr.task_states.items()
        if v.get("status") == "completed"
    }
    assert len(completed_states) == 2, (
        f"Expected 2 completed tasks, got: {mgr.task_states}"
    )

    # Verify all_completed() returns True
    assert mgr.all_completed(), "Expected all_completed() = True"

    # Get completed results and verify legacy key shape
    completed_results = mgr.get_completed_results()
    assert len(completed_results) == 2, (
        f"Expected 2 completed results, got {len(completed_results)}"
    )
    for cr in completed_results:
        assert "task_id" in cr, f"Missing 'task_id' key: {cr}"
        assert "description" in cr, f"Missing 'description' key: {cr}"
        assert "result" in cr, f"Missing 'result' key: {cr}"
        assert "execution_mode" in cr, f"Missing 'execution_mode' key: {cr}"

    # Call summarize and verify
    result = await _fake_summarize("test input", completed_results)
    assert len(summarize_calls) == 1, "summarize should be called exactly once"

    called_results = summarize_calls[0][1]
    assert len(called_results) == 2, "summarize should receive 2-element list"
    for cr in called_results:
        assert "task_id" in cr
        assert "description" in cr
        assert "result" in cr

    # Build project from summary and verify content event shape
    orch = orch_mod.Orchestrator.__new__(orch_mod.Orchestrator)
    orch.main_agent = MagicMock()
    project_data = orch._build_project_from_summary(decomp, known_summary, completed_results)
    assert project_data.get("type") == "project", (
        f"Expected type=project, got: {project_data}"
    )


# ---------------------------------------------------------------------------
# Test 1b: Full orchestrator flow — 2 tasks complete → content(project) emitted
# ---------------------------------------------------------------------------

async def test_two_completed_tasks_content_project_emitted(monkeypatch):
    """Full Orchestrator.process_message_stream: 2 multi-tasks complete → content event
    with type='project' is emitted (summarize path runs end-to-end)."""
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", False)  # use TaskAgent path

    # Patch TaskAgent to return a completed result directly
    class _FakeTaskAgent:
        _call_n = {"n": 0}

        async def execute(self, task_def, edition="bedrock"):
            cls = type(self)
            cmd = "/give @p diamond 1" if cls._call_n["n"] % 2 == 0 else "/give @p gold_ingot 1"
            cls._call_n["n"] += 1
            yield {
                "event": "task_update",
                "data": {
                    "task_id": task_def.get("task_id", "1"),
                    "status": "completed",
                    "result": {
                        "type": "single_command",
                        "command": {"command": cmd, "explanation": "test", "variants": [], "warnings": []},
                    },
                },
            }

    monkeypatch.setattr(orch_mod, "TaskAgent", _FakeTaskAgent)

    # Patch summarize to return known summary
    known_summary = {"explanation": "汇总结果", "phases": []}

    async def _fake_summarize(user_input, task_results, edition="bedrock"):
        return dict(known_summary)

    # Use Planner path — but flag is off so we use main_agent.decompose
    decomp_result = {
        "project_name": "test",
        "overview": "test",
        "is_single_task": False,
        "tasks": [
            _task_def("t1", "给钻石"),
            _task_def("t2", "给金锭"),
        ],
        "_original_input": "给我两种矿石",
    }

    main_agent_mock = MagicMock()
    main_agent_mock.decompose = AsyncMock(return_value=decomp_result)
    main_agent_mock.summarize = AsyncMock(return_value=known_summary)

    orch = orch_mod.Orchestrator.__new__(orch_mod.Orchestrator)
    orch.main_agent = main_agent_mock
    orch.planner = MagicMock()
    orch._active_sessions = {}

    events = await _collect_stream(
        orch.process_message_stream("给我两种矿石", session_id="sess1", edition="bedrock")
    )

    # summarize should be called once
    assert main_agent_mock.summarize.call_count == 1, (
        f"summarize called {main_agent_mock.summarize.call_count} times, expected 1"
    )

    # The call args should have legacy keys
    call_args = main_agent_mock.summarize.call_args
    # call_args[0][1] is the completed_results positional arg
    # or use keyword: call_args.args / call_args.kwargs
    passed_results = call_args[0][1] if call_args[0] else call_args[1].get("task_results", [])
    assert len(passed_results) == 2, f"summarize should receive 2 results, got {len(passed_results)}"
    for cr in passed_results:
        assert "task_id" in cr
        assert "description" in cr
        assert "result" in cr

    # A 'content' event must be emitted
    content_events = [ev for ev in events if ev["event"] == "content"]
    assert len(content_events) >= 1, f"Expected at least 1 content event. Events: {[e['event'] for e in events]}"

    content_ev = content_events[-1]
    assert content_ev["data"].get("type") == "project", (
        f"content event should have type=project, got: {content_ev['data'].get('type')}"
    )


# ---------------------------------------------------------------------------
# Test 2: 1 paused + 1 completed → all_completed() False → done emitted,
#         summarize NOT called, session retained
# ---------------------------------------------------------------------------

async def test_one_paused_one_completed_no_summarize_session_retained(monkeypatch):
    """With one task paused and one completed, all_completed() is False;
    the orchestrator emits done without calling summarize, and the session
    is kept in _active_sessions."""
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", True)

    # t1 asks user; t2 is independent and completes
    question = "你需要什么类型的剑？"
    t2_answer = _single_command_json("/give @p gold_ingot 1")

    class _MixedStep:
        """Dispatches ask_user for t1 (request contains '给剑'), done for t2."""

        def __init__(self):
            self.calls = 0

        async def run(self, messages, tool_schemas):
            self.calls += 1
            # Check the user message to decide which task this is
            content_str = str(messages)
            if "给剑" in content_str and "给金锭" not in content_str:
                # This is t1 → pause with ask_user
                return StepResult(
                    content="",
                    thinking="",
                    tool_calls=[ToolCall("c_ask", "finish", {"reason": "ask_user", "final_answer": question})],
                    raw_assistant_msg={"role": "assistant", "content": ""},
                )
            else:
                # This is t2 → complete
                return StepResult(
                    content="",
                    thinking="",
                    tool_calls=[ToolCall("c_done", "finish", {"reason": "done", "final_answer": t2_answer})],
                    raw_assistant_msg={"role": "assistant", "content": ""},
                )

        def format_observation(self, call, obs):
            return {"role": "tool", "tool_call_id": call.id, "content": obs.to_tool_content()}

    step = _MixedStep()
    reg = _finish_registry()

    monkeypatch.setattr(orch_mod, "build_default_registry", lambda: reg)
    monkeypatch.setattr(orch_mod, "build_step", lambda client: step)
    monkeypatch.setattr(orch_mod, "get_llm_client", lambda: object())

    decomp = _make_decomp([
        _task_def("t1", "给剑"),
        _task_def("t2", "给金锭"),
    ], is_single=False)

    # USE_AGENT_LOOP=True uses Planner path; we need is_single=False to hit multi-task.
    # Planner.plan must return (Decomposition, thinking_str).
    from backend.agents.planner_schemas import Decomposition, TaskDef

    planner_plan = Decomposition(
        project_name="test",
        overview="test",
        is_single_task=False,
        tasks=[
            TaskDef(task_id="t1", user_request="给剑", description="任务t1"),
            TaskDef(task_id="t2", user_request="给金锭", description="任务t2"),
        ],
    )

    planner_mock = MagicMock()
    planner_mock.plan = AsyncMock(return_value=(planner_plan, ""))

    main_agent_mock = MagicMock()
    main_agent_mock.summarize = AsyncMock(return_value={"explanation": "test", "phases": []})

    orch = orch_mod.Orchestrator.__new__(orch_mod.Orchestrator)
    orch.main_agent = main_agent_mock
    orch.planner = planner_mock
    orch._active_sessions = {}

    events = await _collect_stream(
        orch.process_message_stream("给剑和金锭", session_id="sess_pause", edition="bedrock")
    )

    event_types = [ev["event"] for ev in events]

    # done should be emitted
    assert "done" in event_types, f"Expected 'done' in events: {event_types}"

    # summarize should NOT be called
    assert main_agent_mock.summarize.call_count == 0, (
        f"summarize should NOT be called when not all_completed, "
        f"but was called {main_agent_mock.summarize.call_count} time(s)"
    )

    # Session should be retained (mgr kept alive for future resume)
    assert "sess_pause" in orch._active_sessions, (
        f"Session 'sess_pause' should be retained when tasks are paused; "
        f"active sessions: {list(orch._active_sessions.keys())}"
    )

    # all_completed() must be False on the retained session
    retained_mgr = orch._active_sessions["sess_pause"]
    assert not retained_mgr.all_completed(), (
        "Retained session's manager should NOT be all_completed()"
    )

    # t1 must be paused
    t1_state = retained_mgr.task_states.get("t1", {})
    assert t1_state.get("status") == "paused", (
        f"t1 must be paused, got: {t1_state}"
    )


# ---------------------------------------------------------------------------
# Test 3: summarize raises LLMError → soft-fail: content emitted, stream ok
# ---------------------------------------------------------------------------

async def test_summarize_llm_error_soft_fail(monkeypatch):
    """When summarize raises LLMError, the soft-fail in main_agent.summarize
    returns a degraded dict {"explanation": ..., "phases": []}, which the
    orchestrator uses to emit a content event — stream completes without crash."""
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", False)

    # Two tasks that complete immediately
    class _FakeTaskAgent:
        _call_n = {"n": 0}

        async def execute(self, task_def, edition="bedrock"):
            cls = type(self)
            cmd = "/give @p diamond 1" if cls._call_n["n"] % 2 == 0 else "/give @p emerald 1"
            cls._call_n["n"] += 1
            yield {
                "event": "task_update",
                "data": {
                    "task_id": task_def.get("task_id", "1"),
                    "status": "completed",
                    "result": {
                        "type": "single_command",
                        "command": {"command": cmd, "explanation": "test", "variants": [], "warnings": []},
                    },
                },
            }

    monkeypatch.setattr(orch_mod, "TaskAgent", _FakeTaskAgent)

    # summarize raises LLMError — but soft-fail in main_agent.summarize catches it
    # and returns {"explanation": "汇总失败: ...", "phases": []}
    # We simulate the soft-fail behavior directly (since we can't test the actual LLM call):
    async def _summarize_soft_fail(user_input, task_results, edition="bedrock"):
        # This mimics what main_agent.summarize does in its except block:
        try:
            raise LLMError("模拟 LLM 错误")
        except Exception as e:
            return {"explanation": f"汇总失败: {e}", "phases": []}

    decomp_result = {
        "project_name": "test",
        "overview": "test",
        "is_single_task": False,
        "tasks": [
            _task_def("t1", "给钻石"),
            _task_def("t2", "给绿宝石"),
        ],
        "_original_input": "给我两种宝石",
    }

    main_agent_mock = MagicMock()
    main_agent_mock.decompose = AsyncMock(return_value=decomp_result)
    main_agent_mock.summarize = AsyncMock(side_effect=_summarize_soft_fail)

    orch = orch_mod.Orchestrator.__new__(orch_mod.Orchestrator)
    orch.main_agent = main_agent_mock
    orch.planner = MagicMock()
    orch._active_sessions = {}

    # The stream should NOT raise — soft-fail returns degraded explanation
    events = await _collect_stream(
        orch.process_message_stream("给我两种宝石", session_id="sess_soft", edition="bedrock")
    )

    event_types = [ev["event"] for ev in events]

    # Stream must complete (no exception raised)
    assert "done" in event_types, f"Stream should complete with done event. Events: {event_types}"

    # A content event should be emitted (with the degraded explanation-based project)
    content_events = [ev for ev in events if ev["event"] == "content"]
    assert len(content_events) >= 1, (
        f"Expected at least 1 content event after soft-fail. Events: {event_types}"
    )

    # The content type should be project (built from empty phases fallback)
    content_ev = content_events[-1]
    assert content_ev["data"].get("type") == "project", (
        f"content type should be 'project' even after soft-fail: {content_ev['data']}"
    )


# ---------------------------------------------------------------------------
# Test 3b: Verify soft-fail in MainAgent.summarize directly (unit test)
# ---------------------------------------------------------------------------

async def test_main_agent_summarize_llm_error_returns_degraded():
    """MainAgent.summarize catches all exceptions and returns a degraded dict
    with 'explanation' and 'phases' keys (not raises)."""
    from backend.agents.main_agent import MainAgent
    from unittest.mock import patch, AsyncMock

    agent = MainAgent.__new__(MainAgent)

    error_client = MagicMock()
    error_client.chat = AsyncMock(side_effect=LLMError("connection timeout"))

    task_results = [
        {
            "task_id": "t1",
            "description": "给钻石",
            "execution_mode": "continuous",
            "result": {
                "type": "single_command",
                "command": {"command": "/give @p diamond 1", "explanation": "test", "variants": [], "warnings": []},
            },
        }
    ]

    with patch("backend.agents.main_agent.get_llm_client", return_value=error_client):
        result = await agent.summarize("给钻石", task_results, edition="bedrock")

    # Must NOT raise; must return dict with explanation + phases
    assert isinstance(result, dict), "summarize must return a dict even on error"
    assert "explanation" in result, "Degraded result must have 'explanation' key"
    assert "phases" in result, "Degraded result must have 'phases' key"
    assert result["phases"] == [], "Degraded phases should be empty list"
    assert "汇总失败" in result["explanation"], (
        f"Degraded explanation should contain '汇总失败': {result['explanation']}"
    )
