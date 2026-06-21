"""Tests for orchestrator single-task AgentLoop branch (Task 6).

Three acceptance gates:
(a) flag-off → _run_single_task_loop NOT called (existing TaskManager path)
(b) flag-on single-task DONE → event order: task_list → task_update(generating)
    → [task_thinking*] → task_update(validating) → content → done,
    with content.data.type == "single_command"
(c) flag-on ASK_USER → task_update(paused) + done, no validating/content
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

def _make_outcome(reason: str, content: str, thinking: str = "") -> AgentOutcome:
    return AgentOutcome(
        reason=FinishReason(reason),
        content=content,
        thinking=thinking,
        observations=[],
        rounds_used=1,
    )


class _ScriptStep:
    """Returns scripted StepResult objects round by round."""

    def __init__(self, script: list[StepResult]) -> None:
        self._script = script
        self.calls = 0

    async def run(self, messages, tool_schemas):
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


def _single_command_json(cmd: str = "/give @p diamond 1") -> str:
    return json.dumps({
        "type": "single_command",
        "command": {
            "command": cmd,
            "explanation": "给钻石",
            "variants": [],
            "warnings": [],
        },
    })


async def _collect_stream(gen) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async for ev in gen:
        events.append(ev)
    return events


# ---------------------------------------------------------------------------
# Fixtures: mock main_agent.decompose so we don't hit real LLM
# ---------------------------------------------------------------------------

def _single_task_decomposition(user_request: str = "给钻石") -> dict[str, Any]:
    return {
        "is_single_task": True,
        "project_name": "",
        "overview": "",
        "tasks": [
            {
                "task_id": "1",
                "user_request": user_request,
                "output_type": "simple_command",
                "description": "给玩家钻石",
                "recommended_commands": [],
                "depends_on": [],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Test (a): flag-off → _run_single_task_loop NOT called
# ---------------------------------------------------------------------------

async def test_flag_off_does_not_use_loop(monkeypatch):
    """With USE_AGENT_LOOP=False, _run_single_task_loop must never be called."""
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", False)

    called = {"n": 0}

    # Patch decompose to return a single-task decomposition
    async def fake_decompose(user_input, session_context, edition="bedrock"):
        return _single_task_decomposition(user_input)

    # Patch _run_single_task_loop to track if it's called
    async def _spy_run_single(*args, **kwargs):
        called["n"] += 1
        # Should never reach here
        if False:
            yield {}

    from backend.orchestrator.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch.main_agent = type("MA", (), {"decompose": staticmethod(fake_decompose)})()
    orch._active_sessions = {}
    orch._run_single_task_loop = _spy_run_single

    # Also patch TaskManager to avoid actual TaskAgent execution
    executed = {"n": 0}

    class _FakeTaskManager:
        def __init__(self, decomp, edition="bedrock"):
            self.decomposition = decomp
            self.edition = edition
            self._task_states = {}

        def is_expired(self):
            return False

        def all_completed(self):
            executed["n"] += 1
            return True

        def get_completed_results(self):
            return [{"task_id": "1", "description": "test", "result": {
                "type": "single_command",
                "command": {"command": "/give @p diamond 1", "explanation": "", "variants": [], "warnings": []},
            }}]

        async def execute_all(self):
            if False:
                yield {}

    monkeypatch.setattr(orch_mod, "TaskManager", _FakeTaskManager)

    events = await _collect_stream(
        orch.process_message_stream("给钻石", session_id="sess1")
    )

    assert called["n"] == 0, "_run_single_task_loop was called despite USE_AGENT_LOOP=False"
    # And the existing path ran (TaskManager was constructed)
    assert executed["n"] >= 1


# ---------------------------------------------------------------------------
# Test (b): flag-on, single-task DONE → correct event order
# ---------------------------------------------------------------------------

async def test_flag_on_single_task_done_event_order(monkeypatch):
    """With USE_AGENT_LOOP=True + single task + DONE finish, check event order."""
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", True)

    # Decompose returns single task
    async def fake_decompose(user_input, session_context, edition="bedrock"):
        return _single_task_decomposition(user_input)

    # Scripted step: immediately finish(done, <valid json>)
    answer = _single_command_json()
    step = _ScriptStep([
        StepResult(
            content="",
            thinking="",
            tool_calls=[ToolCall("c1", "finish", {"reason": "done", "final_answer": answer})],
            raw_assistant_msg={"role": "assistant", "content": ""},
        )
    ])
    reg = _finish_registry(reason="done", answer=answer)

    # Patch build_default_registry and build_step to return our scripted versions
    monkeypatch.setattr(orch_mod, "build_default_registry", lambda: reg)
    monkeypatch.setattr(orch_mod, "build_step", lambda client: step)
    # Patch get_llm_client to return something (step doesn't actually use it)
    monkeypatch.setattr(orch_mod, "get_llm_client", lambda: object())

    from backend.orchestrator.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch.main_agent = type("MA", (), {"decompose": staticmethod(fake_decompose)})()
    orch._active_sessions = {}

    events = await _collect_stream(
        orch.process_message_stream("给我钻石", session_id="sess2")
    )

    event_types = [ev["event"] for ev in events]

    # Required events in order
    assert "task_list" in event_types, f"Missing task_list. Events: {event_types}"
    assert "done" in event_types, f"Missing done. Events: {event_types}"
    assert "content" in event_types, f"Missing content. Events: {event_types}"

    # Find first indices
    task_list_idx = event_types.index("task_list")
    done_idx = event_types.index("done")
    content_idx = event_types.index("content")

    # task_update(generating) appears after task_list
    generating_idx = next(
        (i for i, ev in enumerate(events)
         if ev["event"] == "task_update" and ev.get("data", {}).get("status") == "generating"),
        None,
    )
    assert generating_idx is not None, "Missing task_update(generating)"
    assert generating_idx > task_list_idx, "task_update(generating) must come after task_list"

    # task_update(validating) appears before content
    validating_idx = next(
        (i for i, ev in enumerate(events)
         if ev["event"] == "task_update" and ev.get("data", {}).get("status") == "validating"),
        None,
    )
    assert validating_idx is not None, "Missing task_update(validating)"
    assert validating_idx < content_idx, "task_update(validating) must come before content"
    assert content_idx < done_idx, "content must come before done"

    # task_update(completed) appears BETWEEN validating and content (I1 fix)
    completed_idx = next(
        (i for i, ev in enumerate(events)
         if ev["event"] == "task_update" and ev.get("data", {}).get("status") == "completed"),
        None,
    )
    assert completed_idx is not None, "Missing task_update(completed) — frontend spinner relies on it"
    assert validating_idx < completed_idx < content_idx, (
        f"task_update(completed) must be between validating ({validating_idx}) "        f"and content ({content_idx}), got {completed_idx}"
    )
    # completed event must carry result
    completed_ev = events[completed_idx]
    assert "result" in completed_ev["data"], "task_update(completed) must carry result"

    # content.data.type == "single_command"
    content_ev = events[content_idx]
    assert content_ev["data"].get("type") == "single_command", (
        f"content.data.type expected 'single_command', got: {content_ev['data']}"
    )


# ---------------------------------------------------------------------------
# Test (c): flag-on, ASK_USER → paused + done, no validating/content
# ---------------------------------------------------------------------------

async def test_flag_on_ask_user_pauses(monkeypatch):
    """With ASK_USER outcome, emit task_update(paused) and done; no validating/content."""
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", True)

    async def fake_decompose(user_input, session_context, edition="bedrock"):
        return _single_task_decomposition(user_input)

    # Scripted step: finish(ask_user, question text)
    question = "你要钻石剑还是铁剑？"
    step = _ScriptStep([
        StepResult(
            content="",
            thinking="",
            tool_calls=[ToolCall("c1", "finish", {"reason": "ask_user", "final_answer": question})],
            raw_assistant_msg={"role": "assistant", "content": ""},
        )
    ])
    reg = _finish_registry(reason="ask_user", answer=question)

    monkeypatch.setattr(orch_mod, "build_default_registry", lambda: reg)
    monkeypatch.setattr(orch_mod, "build_step", lambda client: step)
    monkeypatch.setattr(orch_mod, "get_llm_client", lambda: object())

    from backend.orchestrator.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch.main_agent = type("MA", (), {"decompose": staticmethod(fake_decompose)})()
    orch._active_sessions = {}

    events = await _collect_stream(
        orch.process_message_stream("我要剑", session_id="sess3")
    )

    event_types = [ev["event"] for ev in events]

    # Must have task_update(paused)
    paused_ev = next(
        (ev for ev in events
         if ev["event"] == "task_update" and ev.get("data", {}).get("status") == "paused"),
        None,
    )
    assert paused_ev is not None, f"Missing task_update(paused). Events: {event_types}"

    # paused result must be conversation type
    paused_result = paused_ev.get("data", {}).get("result", {})
    assert paused_result.get("type") == "conversation", (
        f"paused result type expected 'conversation', got: {paused_result}"
    )

    # Must have done
    assert "done" in event_types, f"Missing done. Events: {event_types}"

    # Must NOT have task_update(validating)
    has_validating = any(
        ev["event"] == "task_update" and ev.get("data", {}).get("status") == "validating"
        for ev in events
    )
    assert not has_validating, "ASK_USER path must NOT emit task_update(validating)"

    # Must NOT have content
    assert "content" not in event_types, "ASK_USER path must NOT emit content"
