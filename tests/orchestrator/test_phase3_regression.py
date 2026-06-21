"""Phase 3 regression gates (Task 6).

Five gates:
1. flag-off multi-task: USE_AGENT_LOOP=False — Planner.plan NEVER called; full event
   sequence matches golden (task_list → task_update* → content → done).
2. flag-on happy path: client.chat returns valid decomposition JSON; build_step/
   build_default_registry scripted; task_list ids match planner JSON, content(project)+done.
3. flag-on invalid-graph repair: client.chat returns CYCLIC first, clean second →
   client.chat called twice; stream produces valid task_list and completes; no fabricated
   single task.
4. flag-on hard failure (UX change): client.chat ALWAYS cyclic → PlannerParseError →
   orchestrator emits error event, NOT a fake single-task task_list.
5. flag-on transport failure: client.chat raises TransientLLMError → error event, not fake
   task.

Note on patching strategy (gates 2-5):
  Planner.plan imports get_llm_client from backend.subscription.llm_context, but binds
  it locally as `backend.agents.planner.get_llm_client`. We patch that local binding so
  the Planner's LLM calls go through our fake client.
"""

from __future__ import annotations

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
from backend.llm.errors import TransientLLMError


# ---------------------------------------------------------------------------
# Helpers (shared with test_multitask_loop.py)
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


def _finish_registry() -> ToolRegistry:
    """Mini registry with only finish handler."""
    reg = ToolRegistry()

    async def finish_handler(args: dict, ctx: ToolContext) -> Observation:
        return Observation(
            tool_name="finish",
            ok=True,
            summary="finish",
            data={
                "reason": args.get("reason", "done"),
                "final_answer": args.get("final_answer", ""),
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


def _make_chat_response(content: str) -> dict[str, Any]:
    """Build the dict shape client.chat returns."""
    return {"message": {"content": content, "thinking": ""}}


def _valid_decomp_json(task_ids: list[str]) -> str:
    """Build a minimal valid decomposition JSON string for the given task ids."""
    tasks = [
        {
            "task_id": tid,
            "user_request": f"请求{tid}",
            "description": f"任务{tid}",
            "output_type": "simple_command",
            "recommended_commands": [],
            "depends_on": [],
            "execution_mode": "continuous",
        }
        for tid in task_ids
    ]
    return json.dumps({
        "project_name": "测试项目",
        "overview": "测试概览",
        "is_single_task": len(task_ids) == 1,
        "tasks": tasks,
    })


def _cyclic_decomp_json() -> str:
    """Build a decomposition JSON with a cycle (t1 → t2 → t1)."""
    return json.dumps({
        "project_name": "循环项目",
        "overview": "包含循环依赖",
        "is_single_task": False,
        "tasks": [
            {
                "task_id": "t1",
                "user_request": "请求t1",
                "description": "任务t1",
                "output_type": "simple_command",
                "recommended_commands": [],
                "depends_on": ["t2"],  # t1 → t2
                "execution_mode": "continuous",
            },
            {
                "task_id": "t2",
                "user_request": "请求t2",
                "description": "任务t2",
                "output_type": "simple_command",
                "recommended_commands": [],
                "depends_on": ["t1"],  # t2 → t1 : cycle!
                "execution_mode": "continuous",
            },
        ],
    })


class _ScriptedStep:
    """Returns a scripted sequence of StepResults."""

    def __init__(self, answers: list[str]) -> None:
        self._answers = answers
        self.calls = 0

    async def run(self, messages, tool_schemas):
        ans = self._answers[min(self.calls, len(self._answers) - 1)]
        self.calls += 1
        return StepResult(
            content="",
            thinking="",
            tool_calls=[ToolCall(f"c{self.calls}", "finish", {"reason": "done", "final_answer": ans})],
            raw_assistant_msg={"role": "assistant", "content": ""},
        )

    def format_observation(self, call, obs):
        return {"role": "tool", "tool_call_id": call.id, "content": obs.to_tool_content()}


# ---------------------------------------------------------------------------
# Gate 1: flag-OFF multi-task — Planner.plan NEVER called, golden event sequence
# ---------------------------------------------------------------------------


async def test_flag_off_planner_never_called_golden_sequence(monkeypatch):
    """USE_AGENT_LOOP=False: Planner.plan must be never called.
    Full event sequence must match golden: thinking* → task_list → task_update* →
    thinking* → content → done (order-insensitive for thinking events; structural
    check for task_list + task_update + content + done).
    """
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", False)

    # Fixed 2-task decomposition from MainAgent.decompose
    decomp_result = {
        "project_name": "钻石项目",
        "overview": "给两种矿石",
        "is_single_task": False,
        "tasks": [
            _task_def("t1", "给钻石"),
            _task_def("t2", "给金锭"),
        ],
        "_original_input": "给两种矿石",
    }

    # Track Planner.plan calls
    planner_plan_called = {"n": 0}

    class _SpyPlanner:
        async def plan(self, user_input, session_context="", **kwargs):
            planner_plan_called["n"] += 1
            raise AssertionError("Planner.plan must NOT be called when USE_AGENT_LOOP=False")

    # TaskAgent scripted: t1 → complete with diamond, t2 → complete with gold
    call_n = {"n": 0}

    class _ScriptedTaskAgent:
        async def execute(self, task_def, edition="bedrock"):
            cmd = "/give @p diamond 1" if call_n["n"] % 2 == 0 else "/give @p gold_ingot 1"
            call_n["n"] += 1
            yield {
                "event": "task_update",
                "data": {
                    "task_id": task_def.get("task_id", "1"),
                    "status": "completed",
                    "result": {
                        "type": "single_command",
                        "command": {
                            "command": cmd,
                            "explanation": "测试",
                            "variants": [],
                            "warnings": [],
                        },
                    },
                },
            }

    monkeypatch.setattr(orch_mod, "TaskAgent", _ScriptedTaskAgent)

    main_agent_mock = MagicMock()
    main_agent_mock.decompose = AsyncMock(return_value=decomp_result)
    # summarize is needed for multi-task
    main_agent_mock.summarize = AsyncMock(return_value={
        "explanation": "两个任务完成",
        "phases": [],
    })

    orch = orch_mod.Orchestrator.__new__(orch_mod.Orchestrator)
    orch.main_agent = main_agent_mock
    orch.planner = _SpyPlanner()
    orch._active_sessions = {}

    events = await _collect_stream(
        orch.process_message_stream("给两种矿石", session_id="sess_off", edition="bedrock")
    )

    # Gate 1a: Planner.plan must NEVER have been called
    assert planner_plan_called["n"] == 0, (
        f"Planner.plan was called {planner_plan_called['n']} time(s) but must be 0 "
        "when USE_AGENT_LOOP=False"
    )

    # Gate 1b: MainAgent.decompose must be called once
    assert main_agent_mock.decompose.call_count == 1, (
        f"MainAgent.decompose should be called once, got {main_agent_mock.decompose.call_count}"
    )

    event_types = [ev["event"] for ev in events]

    # Gate 1c: task_list must be emitted
    assert "task_list" in event_types, f"Expected task_list event. Got: {event_types}"

    # Gate 1d: task_update events emitted (at least 2 completed)
    completed_updates = [
        ev for ev in events
        if ev["event"] == "task_update" and ev.get("data", {}).get("status") == "completed"
    ]
    assert len(completed_updates) == 2, (
        f"Expected 2 completed task_update events, got {len(completed_updates)}"
    )

    # Gate 1e: content event present
    assert "content" in event_types, f"Expected content event. Got: {event_types}"

    # Gate 1f: done event present
    assert "done" in event_types, f"Expected done event. Got: {event_types}"

    # Gate 1g: structural order: task_list before first task_update before content before done
    task_list_idx = event_types.index("task_list")
    first_update_idx = next(i for i, t in enumerate(event_types) if t == "task_update")
    content_idx = event_types.index("content")
    done_idx = event_types.index("done")

    assert task_list_idx < first_update_idx, "task_list must come before first task_update"
    assert first_update_idx < content_idx, "task_update must come before content"
    assert content_idx < done_idx, "content must come before done"

    # Gate 1h: task_list contains the correct 2 task ids
    task_list_ev = next(ev for ev in events if ev["event"] == "task_list")
    task_ids_in_list = {t["task_id"] for t in task_list_ev["data"]["tasks"]}
    assert task_ids_in_list == {"t1", "t2"}, (
        f"task_list must contain t1 and t2, got: {task_ids_in_list}"
    )

    # Gate 1i: no error event
    assert "error" not in event_types, f"Unexpected error event in flag-OFF path: {event_types}"


# ---------------------------------------------------------------------------
# Gate 2: flag-ON happy path — client.chat returns valid decomp; tasks complete; content+done
# ---------------------------------------------------------------------------


async def test_flag_on_happy_path_planner_json_ids_match(monkeypatch):
    """USE_AGENT_LOOP=True: client.chat returns valid 2-task decomposition JSON.
    task_list task ids must match planner JSON; tasks execute; content(project)+done emitted.
    """
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", True)

    task_ids = ["p1", "p2"]
    valid_json = _valid_decomp_json(task_ids)

    # client.chat always returns valid decomposition.
    # Patch backend.agents.planner.get_llm_client (where Planner imported it).
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(return_value=_make_chat_response(valid_json))
    monkeypatch.setattr("backend.agents.planner.get_llm_client", lambda: fake_client)

    # AgentLoop step: always finishes immediately with a single command
    answers = [
        _single_command_json("/give @p diamond 1"),
        _single_command_json("/give @p emerald 1"),
    ]
    step = _ScriptedStep(answers)
    reg = _finish_registry()

    monkeypatch.setattr(orch_mod, "build_default_registry", lambda: reg)
    monkeypatch.setattr(orch_mod, "build_step", lambda client: step)

    # summarize for multi-task project
    main_agent_mock = MagicMock()
    main_agent_mock.summarize = AsyncMock(return_value={
        "explanation": "两任务完成",
        "phases": [],
    })

    orch = orch_mod.Orchestrator.__new__(orch_mod.Orchestrator)
    orch.main_agent = main_agent_mock
    orch.planner = orch_mod.Planner()
    orch._active_sessions = {}

    events = await _collect_stream(
        orch.process_message_stream("给我钻石和绿宝石", session_id="sess_happy", edition="bedrock")
    )

    event_types = [ev["event"] for ev in events]

    # Gate 2a: no error
    assert "error" not in event_types, f"Unexpected error in happy path: {events}"

    # Gate 2b: task_list present with ids matching planner JSON
    assert "task_list" in event_types, f"Expected task_list. Got: {event_types}"
    task_list_ev = next(ev for ev in events if ev["event"] == "task_list")
    actual_ids = {t["task_id"] for t in task_list_ev["data"]["tasks"]}
    assert actual_ids == set(task_ids), (
        f"task_list ids {actual_ids} must match planner JSON ids {set(task_ids)}"
    )

    # Gate 2c: both tasks complete
    completed_updates = [
        ev for ev in events
        if ev["event"] == "task_update" and ev.get("data", {}).get("status") == "completed"
    ]
    assert len(completed_updates) == 2, (
        f"Expected 2 completed task_update events, got {len(completed_updates)}"
    )

    # Gate 2d: content event present
    assert "content" in event_types, f"Expected content event. Got: {event_types}"
    content_ev = next(ev for ev in events if ev["event"] == "content")
    # project type (multi-task)
    assert content_ev["data"].get("type") == "project", (
        f"content should be type=project for multi-task, got: {content_ev['data'].get('type')}"
    )

    # Gate 2e: done event
    assert "done" in event_types, f"Expected done event. Got: {event_types}"


# ---------------------------------------------------------------------------
# Gate 3: flag-ON invalid-graph repair — cyclic first, clean second → 2 chat calls
# ---------------------------------------------------------------------------


async def test_flag_on_invalid_graph_repair_two_chat_calls(monkeypatch):
    """USE_AGENT_LOOP=True: client.chat returns cyclic first call, valid second call.
    Assert client.chat called exactly twice (1 plan + 1 repair), stream produces valid
    task_list and completes, no fabricated single task appears.
    """
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", True)

    cyclic_json = _cyclic_decomp_json()
    valid_json = _valid_decomp_json(["r1", "r2"])

    chat_call_count = {"n": 0}

    async def _scripted_chat(messages, **kwargs):
        chat_call_count["n"] += 1
        if chat_call_count["n"] == 1:
            return _make_chat_response(cyclic_json)
        else:
            return _make_chat_response(valid_json)

    fake_client = MagicMock()
    fake_client.chat = _scripted_chat
    # Patch where Planner imported get_llm_client
    monkeypatch.setattr("backend.agents.planner.get_llm_client", lambda: fake_client)

    # AgentLoop step: always finishes with single command
    step = _ScriptedStep([
        _single_command_json("/give @p diamond 1"),
        _single_command_json("/give @p emerald 1"),
    ])
    reg = _finish_registry()

    monkeypatch.setattr(orch_mod, "build_default_registry", lambda: reg)
    monkeypatch.setattr(orch_mod, "build_step", lambda client: step)

    main_agent_mock = MagicMock()
    main_agent_mock.summarize = AsyncMock(return_value={
        "explanation": "修复后完成",
        "phases": [],
    })

    orch = orch_mod.Orchestrator.__new__(orch_mod.Orchestrator)
    orch.main_agent = main_agent_mock
    orch.planner = orch_mod.Planner()
    orch._active_sessions = {}

    events = await _collect_stream(
        orch.process_message_stream("循环任务测试", session_id="sess_repair", edition="bedrock")
    )

    event_types = [ev["event"] for ev in events]

    # Gate 3a: client.chat was called exactly twice (plan + 1 repair)
    assert chat_call_count["n"] == 2, (
        f"client.chat should be called 2 times (1 plan + 1 repair), got {chat_call_count['n']}"
    )

    # Gate 3b: stream produced a valid task_list (from the repaired valid_json)
    assert "task_list" in event_types, (
        f"Stream must produce a valid task_list after repair. Got: {event_types}"
    )

    task_list_ev = next(ev for ev in events if ev["event"] == "task_list")
    actual_ids = {t["task_id"] for t in task_list_ev["data"]["tasks"]}
    assert actual_ids == {"r1", "r2"}, (
        f"task_list ids should be from repaired JSON {{r1, r2}}, got: {actual_ids}"
    )

    # Gate 3c: stream completes (done)
    assert "done" in event_types, f"Expected done event after repair. Got: {event_types}"

    # Gate 3d: no error event (repair succeeded)
    assert "error" not in event_types, (
        f"No error event expected when repair succeeds, got: {event_types}"
    )

    # Gate 3e: no fabricated single-task task_list (task_list has 2 real tasks, not 1 fake)
    tasks_in_list = task_list_ev["data"]["tasks"]
    assert len(tasks_in_list) == 2, (
        f"task_list should have 2 repaired tasks, not a fabricated single task: {tasks_in_list}"
    )


# ---------------------------------------------------------------------------
# Gate 4: flag-ON hard failure — always cyclic → PlannerParseError → error event
# ---------------------------------------------------------------------------


async def test_flag_on_hard_failure_always_cyclic_emits_error(monkeypatch):
    """USE_AGENT_LOOP=True: client.chat ALWAYS returns cyclic JSON.
    After max_repairs exhausted, Planner raises PlannerParseError.
    Orchestrator must emit an 'error' event and must NOT emit a task_list with a
    fabricated single task.
    """
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", True)

    cyclic_json = _cyclic_decomp_json()
    chat_call_count = {"n": 0}

    async def _always_cyclic(messages, **kwargs):
        chat_call_count["n"] += 1
        return _make_chat_response(cyclic_json)

    fake_client = MagicMock()
    fake_client.chat = _always_cyclic
    # Patch where Planner imported get_llm_client
    monkeypatch.setattr("backend.agents.planner.get_llm_client", lambda: fake_client)

    orch = orch_mod.Orchestrator.__new__(orch_mod.Orchestrator)
    orch.main_agent = MagicMock()
    orch.planner = orch_mod.Planner()
    orch._active_sessions = {}

    events = await _collect_stream(
        orch.process_message_stream("永久循环测试", session_id="sess_hard_fail", edition="bedrock")
    )

    event_types = [ev["event"] for ev in events]

    # Gate 4a: error event must be emitted
    assert "error" in event_types, (
        f"Expected 'error' event when Planner exhausts repairs. Got: {event_types}"
    )

    # Gate 4b: done event must follow error
    assert "done" in event_types, (
        f"Expected 'done' event after error. Got: {event_types}"
    )
    error_idx = event_types.index("error")
    done_idx = event_types.index("done")
    assert error_idx < done_idx, "error must come before done"

    # Gate 4c: error message must mention task failure
    error_ev = next(ev for ev in events if ev["event"] == "error")
    assert "任务分解失败" in error_ev["data"]["message"], (
        f"Error message should contain '任务分解失败': {error_ev}"
    )

    # Gate 4d: NO task_list with a fabricated single task must appear
    task_list_events = [ev for ev in events if ev["event"] == "task_list"]
    assert len(task_list_events) == 0, (
        f"No task_list should be emitted when Planner hard-fails (no fabricated single task). "
        f"Got task_list events: {task_list_events}"
    )

    # Gate 4e: client.chat was called (1 + max_repairs = 3 times by default)
    # Planner default max_repairs=2, so 3 total attempts
    assert chat_call_count["n"] >= 1, "client.chat must have been called"


# ---------------------------------------------------------------------------
# Gate 5: flag-ON transport failure — TransientLLMError → error event, not fake task
# ---------------------------------------------------------------------------


async def test_flag_on_transport_failure_emits_error_not_fake_task(monkeypatch):
    """USE_AGENT_LOOP=True: client.chat raises TransientLLMError.
    Orchestrator must emit an 'error' event and must NOT emit a task_list with a
    fabricated single task (zero task_list events).
    """
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", True)

    async def _raise_transport(messages, **kwargs):
        raise TransientLLMError("连接超时")

    fake_client = MagicMock()
    fake_client.chat = _raise_transport
    # Patch where Planner imported get_llm_client
    monkeypatch.setattr("backend.agents.planner.get_llm_client", lambda: fake_client)

    orch = orch_mod.Orchestrator.__new__(orch_mod.Orchestrator)
    orch.main_agent = MagicMock()
    orch.planner = orch_mod.Planner()
    orch._active_sessions = {}

    events = await _collect_stream(
        orch.process_message_stream("传输失败测试", session_id="sess_transport", edition="bedrock")
    )

    event_types = [ev["event"] for ev in events]

    # Gate 5a: error event must be emitted
    assert "error" in event_types, (
        f"Expected 'error' event on TransientLLMError. Got: {event_types}"
    )

    # Gate 5b: done event follows error
    assert "done" in event_types, (
        f"Expected 'done' after error. Got: {event_types}"
    )
    error_idx = event_types.index("error")
    done_idx = event_types.index("done")
    assert error_idx < done_idx, "error must come before done"

    # Gate 5c: NO fabricated single-task task_list
    task_list_events = [ev for ev in events if ev["event"] == "task_list"]
    assert len(task_list_events) == 0, (
        f"No task_list should appear on transport failure (no fabricated task). "
        f"Got: {task_list_events}"
    )

    # Gate 5d: error message should mention failure
    error_ev = next(ev for ev in events if ev["event"] == "error")
    assert error_ev["data"].get("message"), (
        f"Error event must carry a message: {error_ev}"
    )
