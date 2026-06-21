"""Tests for TaskManager multi-task AgentLoop branch (Task 4).

Four acceptance gates:
(a) flag-on: 2 independent tasks both complete via AgentLoop (not TaskAgent)
(b) flag-on: dependency injection end-to-end — task2's AgentLoop messages contain
    task1's command (typed predecessor context via _typed_predecessors)
(c) flag-on: task1 ASK_USER → task_update(paused), task2 blocked, done, session kept
(d) semaphore: monkeypatch MAX_PARALLEL_TASKS=1, 3 tier0 tasks run serially
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

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


# ---------------------------------------------------------------------------
# Helpers
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
        "project_name": "test",
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


class _ScriptStep:
    """Returns scripted StepResult objects round by round."""

    def __init__(self, script: list[StepResult]) -> None:
        self._script = script
        self.calls = 0
        self.all_messages: list[list[dict[str, Any]]] = []

    async def run(self, messages, tool_schemas):
        self.all_messages.append(list(messages))
        sr = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        return sr

    def format_observation(self, call, obs):
        return {"role": "tool", "tool_call_id": call.id, "content": obs.to_tool_content()}


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


# ---------------------------------------------------------------------------
# Test (a): flag-on, 2 independent tasks → both completed via AgentLoop
# ---------------------------------------------------------------------------

async def test_flag_on_two_independent_tasks_completed(monkeypatch):
    """Two tasks with no deps both go through AgentLoop and end completed."""
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", True)

    answer1 = _single_command_json("/give @p diamond 1")
    answer2 = _single_command_json("/give @p gold_ingot 1")

    # Track which step is called for which task
    call_count = {"n": 0}

    class _MultiStep:
        """Returns different answers per call pair."""

        def __init__(self) -> None:
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

    step = _MultiStep()
    reg = _finish_registry()

    monkeypatch.setattr(orch_mod, "build_default_registry", lambda: reg)
    monkeypatch.setattr(orch_mod, "build_step", lambda client: step)
    monkeypatch.setattr(orch_mod, "get_llm_client", lambda: object())

    # Verify TaskAgent is NOT called
    task_agent_called = {"n": 0}

    class _FakeTaskAgent:
        async def execute(self, task_def, edition="bedrock"):
            task_agent_called["n"] += 1
            if False:
                yield {}

    monkeypatch.setattr(orch_mod, "TaskAgent", _FakeTaskAgent)

    decomp = _make_decomp([
        _task_def("t1", "给钻石"),
        _task_def("t2", "给金锭"),
    ])
    mgr = orch_mod.TaskManager(decomp, edition="bedrock", use_loop=True)

    events = await _collect_stream(mgr.execute_all())

    # TaskAgent must NOT be called
    assert task_agent_called["n"] == 0, "TaskAgent was called despite use_loop=True"

    # Both tasks should be completed
    completed = [
        ev for ev in events
        if ev["event"] == "task_update" and ev.get("data", {}).get("status") == "completed"
    ]
    assert len(completed) == 2, f"Expected 2 completed events, got {len(completed)}"

    completed_ids = {ev["data"]["task_id"] for ev in completed}
    assert completed_ids == {"t1", "t2"}, f"Unexpected completed ids: {completed_ids}"


# ---------------------------------------------------------------------------
# Test (b): dependency injection end-to-end via _run_via_agentloop
# ---------------------------------------------------------------------------

async def test_flag_on_dependency_injection_e2e(monkeypatch):
    """Task2 depends on task1; task2's AgentLoop messages must contain task1's command.

    This test drives _run_via_agentloop directly after pre-populating _completed_results
    for task1, verifying that _typed_predecessors injects the typed predecessor context
    into the messages seen by task2's AgentLoop step.
    """
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", True)

    t1_cmd = "/give @p diamond 1"
    t1_result = {
        "type": "single_command",
        "command": {
            "command": t1_cmd,
            "explanation": "给钻石",
            "variants": [],
            "warnings": [],
        },
    }
    t2_answer = _single_command_json("/give @p emerald 1")

    # Record all messages seen by the AgentLoop step for task2
    t2_messages_seen: list[list[dict[str, Any]]] = []

    class _RecordingStep:
        def __init__(self) -> None:
            self.calls = 0

        async def run(self, messages, tool_schemas):
            t2_messages_seen.append(list(messages))
            self.calls += 1
            return StepResult(
                content="",
                thinking="",
                tool_calls=[ToolCall(f"c{self.calls}", "finish", {"reason": "done", "final_answer": t2_answer})],
                raw_assistant_msg={"role": "assistant", "content": ""},
            )

        def format_observation(self, call, obs):
            return {"role": "tool", "tool_call_id": call.id, "content": obs.to_tool_content()}

    step = _RecordingStep()
    reg = _finish_registry(reason="done", answer=t2_answer)

    monkeypatch.setattr(orch_mod, "build_default_registry", lambda: reg)
    monkeypatch.setattr(orch_mod, "build_step", lambda client: step)
    monkeypatch.setattr(orch_mod, "get_llm_client", lambda: object())

    # Build manager with t1 already completed, t2 pending
    decomp = _make_decomp([
        _task_def("t1", "给钻石"),
        _task_def("t2", "给绿宝石", depends_on=["t1"]),
    ])
    mgr = orch_mod.TaskManager(decomp, edition="bedrock", use_loop=True)

    # Pre-populate t1 as completed (simulates t1 already ran)
    mgr.task_states["t1"] = {"task_id": "t1", "status": "completed", "result": t1_result}
    mgr._completed_results["t1"] = t1_result

    # Run t2 directly via _run_via_agentloop
    t2_def = _task_def("t2", "给绿宝石", depends_on=["t1"])
    events = await _collect_stream(mgr._run_via_agentloop(t2_def))

    # t2 must complete
    completed = [
        ev for ev in events
        if ev["event"] == "task_update" and ev.get("data", {}).get("status") == "completed"
    ]
    assert len(completed) == 1, f"Expected t2 completed, got: {events}"

    # The messages seen by AgentLoop for t2 must contain t1's command
    all_t2_text = str(t2_messages_seen)
    assert t1_cmd in all_t2_text, (
        f"Task2's AgentLoop messages don't contain task1's command '{t1_cmd}'. "
        f"Messages seen: {t2_messages_seen}"
    )

    # Also verify _typed_predecessors returns the right data directly
    t2_def_for_check = _task_def("t2", "给绿宝石", depends_on=["t1"])
    predecessors = mgr._typed_predecessors(t2_def_for_check)
    assert len(predecessors) == 1, f"Expected 1 predecessor, got {len(predecessors)}"
    assert predecessors[0].task_id == "t1"
    assert t1_cmd in predecessors[0].commands, (
        f"Predecessor should have command '{t1_cmd}'"
    )


# ---------------------------------------------------------------------------
# Test (c): ASK_USER pause → task_update(paused), downstream blocked, done
# ---------------------------------------------------------------------------

async def test_flag_on_ask_user_pause_blocks_downstream(monkeypatch):
    """Task1 ASK_USER → paused; task2 (depends on t1) stays blocked; mgr keeps session."""
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", True)

    question = "你要钻石剑还是铁剑？"

    class _AskStep:
        def __init__(self) -> None:
            self.calls = 0

        async def run(self, messages, tool_schemas):
            self.calls += 1
            return StepResult(
                content="",
                thinking="",
                tool_calls=[ToolCall("c1", "finish", {"reason": "ask_user", "final_answer": question})],
                raw_assistant_msg={"role": "assistant", "content": ""},
            )

        def format_observation(self, call, obs):
            return {"role": "tool", "tool_call_id": call.id, "content": obs.to_tool_content()}

    step = _AskStep()
    reg = _finish_registry(reason="ask_user", answer=question)

    monkeypatch.setattr(orch_mod, "build_default_registry", lambda: reg)
    monkeypatch.setattr(orch_mod, "build_step", lambda client: step)
    monkeypatch.setattr(orch_mod, "get_llm_client", lambda: object())

    decomp = _make_decomp([
        _task_def("t1", "给剑"),
        _task_def("t2", "附魔剑", depends_on=["t1"]),
    ])
    mgr = orch_mod.TaskManager(decomp, edition="bedrock", use_loop=True)
    # Pre-set t2 as blocked so it waits for t1 (mirrors real flow tier behavior)
    mgr.task_states["t2"] = {"task_id": "t2", "status": "blocked"}

    events = await _collect_stream(mgr.execute_all())

    event_types = [ev["event"] for ev in events]

    # Task1 must have paused
    paused_ev = next(
        (ev for ev in events
         if ev["event"] == "task_update"
         and ev.get("data", {}).get("task_id") == "t1"
         and ev.get("data", {}).get("status") == "paused"),
        None,
    )
    assert paused_ev is not None, f"Task1 must be paused. Events: {events}"

    # Task2 must be blocked
    t2_state = mgr.task_states.get("t2", {})
    assert t2_state.get("status") == "blocked", (
        f"Task2 should be blocked but got: {t2_state}"
    )

    # Task2 must NOT be completed
    t2_completed = any(
        ev["event"] == "task_update"
        and ev.get("data", {}).get("task_id") == "t2"
        and ev.get("data", {}).get("status") == "completed"
        for ev in events
    )
    assert not t2_completed, "Task2 must NOT complete when task1 is paused"

    # Session should not be all_completed
    assert not mgr.all_completed(), "Manager should not be all_completed when task is paused"


# ---------------------------------------------------------------------------
# Test (d): Semaphore honored — 3 tier0 tasks with MAX_PARALLEL_TASKS=1 run serially
# ---------------------------------------------------------------------------

async def test_flag_on_semaphore_limits_parallelism(monkeypatch):
    """With MAX_PARALLEL_TASKS=1, 3 independent tasks must run one at a time."""
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", True)
    monkeypatch.setattr(orch_mod, "MAX_PARALLEL_TASKS", 1)

    start_times: list[float] = []
    end_times: list[float] = []

    class _SlowStep:
        def __init__(self) -> None:
            self.calls = 0

        async def run(self, messages, tool_schemas):
            import time as _time
            start_times.append(_time.monotonic())
            await asyncio.sleep(0.01)  # small delay to detect overlap
            end_times.append(_time.monotonic())

            self.calls += 1
            return StepResult(
                content="",
                thinking="",
                tool_calls=[ToolCall(f"c{self.calls}", "finish", {
                    "reason": "done",
                    "final_answer": _single_command_json(f"/say task{self.calls}"),
                })],
                raw_assistant_msg={"role": "assistant", "content": ""},
            )

        def format_observation(self, call, obs):
            return {"role": "tool", "tool_call_id": call.id, "content": obs.to_tool_content()}

    step = _SlowStep()
    reg = _finish_registry()

    monkeypatch.setattr(orch_mod, "build_default_registry", lambda: reg)
    monkeypatch.setattr(orch_mod, "build_step", lambda client: step)
    monkeypatch.setattr(orch_mod, "get_llm_client", lambda: object())

    decomp = _make_decomp([
        _task_def("t1", "任务1"),
        _task_def("t2", "任务2"),
        _task_def("t3", "任务3"),
    ])
    mgr = orch_mod.TaskManager(decomp, edition="bedrock", use_loop=True)

    events = await _collect_stream(mgr.execute_all())

    # All 3 tasks should complete
    completed = [
        ev for ev in events
        if ev["event"] == "task_update" and ev.get("data", {}).get("status") == "completed"
    ]
    assert len(completed) == 3, f"Expected 3 completed, got {len(completed)}"

    # With semaphore=1, no two tasks should overlap: end[i] <= start[i+1]
    assert len(start_times) == 3, f"Expected 3 step runs, got {len(start_times)}"
    for i in range(len(start_times) - 1):
        assert end_times[i] <= start_times[i + 1] + 0.005, (
            f"Tasks overlapped: end[{i}]={end_times[i]:.4f} > start[{i+1}]={start_times[i+1]:.4f}"
        )


# ---------------------------------------------------------------------------
# Test: Planner error branch emits error + done
# ---------------------------------------------------------------------------

async def test_flag_on_planner_error_emits_error_done(monkeypatch):
    """When Planner raises PlannerParseError, orchestrator emits error then done."""
    from backend.agents.planner import PlannerParseError
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", True)

    class _FailPlanner:
        async def plan(self, user_input, session_context, edition="bedrock"):
            raise PlannerParseError("JSON 解析失败")

    from backend.orchestrator.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch.main_agent = None
    orch.planner = _FailPlanner()
    orch._active_sessions = {}

    events = await _collect_stream(
        orch.process_message_stream("任意输入", session_id="sess_err")
    )

    event_types = [ev["event"] for ev in events]

    assert "error" in event_types, f"Expected error event, got: {event_types}"
    assert "done" in event_types, f"Expected done event after error, got: {event_types}"

    error_ev = next(ev for ev in events if ev["event"] == "error")
    assert "任务分解失败" in error_ev["data"]["message"], (
        f"Error message should contain '任务分解失败': {error_ev}"
    )

    # error must come before done
    error_idx = event_types.index("error")
    done_idx = event_types.index("done")
    assert error_idx < done_idx, "error must come before done"


# ---------------------------------------------------------------------------
# Test: resume routing uses _run_one (loop mode)
# ---------------------------------------------------------------------------

async def test_flag_on_resume_uses_run_one(monkeypatch):
    """resume_task goes through _run_one → _run_via_agentloop in loop mode."""
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", True)

    answer = _single_command_json("/give @p iron_sword 1")

    class _ResumeStep:
        def __init__(self) -> None:
            self.calls = 0

        async def run(self, messages, tool_schemas):
            self.calls += 1
            return StepResult(
                content="",
                thinking="",
                tool_calls=[ToolCall("cr1", "finish", {"reason": "done", "final_answer": answer})],
                raw_assistant_msg={"role": "assistant", "content": ""},
            )

        def format_observation(self, call, obs):
            return {"role": "tool", "tool_call_id": call.id, "content": obs.to_tool_content()}

    step = _ResumeStep()
    reg = _finish_registry(reason="done", answer=answer)

    monkeypatch.setattr(orch_mod, "build_default_registry", lambda: reg)
    monkeypatch.setattr(orch_mod, "build_step", lambda client: step)
    monkeypatch.setattr(orch_mod, "get_llm_client", lambda: object())

    # Build a manager with task1 already paused
    decomp = _make_decomp([_task_def("t1", "给剑")])
    mgr = orch_mod.TaskManager(decomp, edition="bedrock", use_loop=True)
    # Simulate that t1 was paused
    mgr.task_states["t1"] = {"task_id": "t1", "status": "paused"}

    task_agent_called = {"n": 0}

    class _FakeTaskAgent:
        async def execute(self, task_def, edition="bedrock"):
            task_agent_called["n"] += 1
            if False:
                yield {}

    monkeypatch.setattr(orch_mod, "TaskAgent", _FakeTaskAgent)

    events = await _collect_stream(mgr.resume_task("t1", "铁剑"))

    # TaskAgent must NOT be called
    assert task_agent_called["n"] == 0, "TaskAgent called despite use_loop=True in resume"

    # AgentLoop step must have been called
    assert step.calls >= 1, "AgentLoop step was not called during resume"

    # t1 should now be completed
    completed = any(
        ev["event"] == "task_update"
        and ev.get("data", {}).get("task_id") == "t1"
        and ev.get("data", {}).get("status") == "completed"
        for ev in events
    )
    assert completed, f"Task1 should be completed after resume. Events: {events}"
