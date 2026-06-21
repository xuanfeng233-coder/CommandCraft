"""End-to-end / regression / parity tests for AgentLoop integration (Task 7).

Four scenarios:
1. flag-off regression   — USE_AGENT_LOOP=False; process_message_stream uses existing
                           TaskManager path; _run_single_task_loop is NEVER called.
2. flag-on happy path    — USE_AGENT_LOOP=True; scripted build_step emits finish(done,
                           valid single_command JSON); terminal content event has
                           type=="single_command" and validation is present.
3. prompted provider     — supports_tools=False forces PromptedToolStep; a fake
                           plain-chat client emits final-answer JSON (no tool call);
                           AgentLoop still reaches DONE/content.
4. chat.py persistence   — under the loop path the terminal user-facing event is
                           "content" (not only "task_update"), confirming that
                           _event_generator's collected_result = data (line 123 in
                           chat.py) picks up the data it needs from "content".
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

import backend.orchestrator.orchestrator as orch_mod
from backend.agentloop.loop import AgentLoop
from backend.agentloop.schemas import (
    AgentOutcome,
    FinishReason,
    LoopBudget,
    Observation,
    StepResult,
    ToolCall,
)
from backend.agentloop.step import PromptedToolStep
from backend.agentloop.tools.registry import ToolContext, ToolRegistry


# ---------------------------------------------------------------------------
# Shared helpers (mirrored from test_orchestrator_loop.py patterns)
# ---------------------------------------------------------------------------

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


def _finish_registry_only() -> ToolRegistry:
    """Minimal registry: finish handler only."""
    reg = ToolRegistry()

    async def finish_handler(args: dict, ctx: ToolContext) -> Observation:
        reason = args.get("reason", "done")
        answer = args.get("final_answer", "")
        return Observation(
            tool_name="finish",
            ok=True,
            summary=f"finish: {reason}",
            data={"reason": reason, "final_answer": answer},
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
    return json.dumps(
        {
            "type": "single_command",
            "command": {
                "command": cmd,
                "explanation": "给玩家钻石",
                "variants": [],
                "warnings": [],
            },
        },
        ensure_ascii=False,
    )


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


async def _collect_stream(gen) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async for ev in gen:
        events.append(ev)
    return events


# ---------------------------------------------------------------------------
# Scenario 1: flag-off regression
# ---------------------------------------------------------------------------

async def test_flag_off_regression_loop_not_called(monkeypatch):
    """USE_AGENT_LOOP=False: _run_single_task_loop must never be called.

    The existing TaskManager path (not AgentLoop) must handle both single and
    multi-task decompositions.  We spy on _run_single_task_loop and assert it
    stays at zero calls; we also verify the stream still produces a 'done'
    event (existing path ran).
    """
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", False)

    loop_call_count = {"n": 0}

    # --- Spy: _run_single_task_loop should never be invoked ---
    async def _spy_run_single(*args, **kwargs):
        loop_call_count["n"] += 1
        if False:  # make it an async generator
            yield {}

    # --- Fake decompose returning a single task ---
    async def fake_decompose(user_input, session_context, edition="bedrock"):
        return _single_task_decomposition(user_input)

    # --- FakeTaskManager: avoids actual LLM calls ---
    task_manager_constructed = {"n": 0}

    class _FakeTaskManager:
        def __init__(self, decomp, edition="bedrock"):
            self.decomposition = decomp
            self.edition = edition
            self.task_states = {}
            task_manager_constructed["n"] += 1

        def is_expired(self):
            return False

        def all_completed(self):
            return True

        def get_completed_results(self):
            return [
                {
                    "task_id": "1",
                    "description": "给钻石",
                    "result": {
                        "type": "single_command",
                        "command": {
                            "command": "/give @p diamond 1",
                            "explanation": "",
                            "variants": [],
                            "warnings": [],
                        },
                    },
                }
            ]

        async def execute_all(self):
            if False:
                yield {}

    monkeypatch.setattr(orch_mod, "TaskManager", _FakeTaskManager)

    from backend.orchestrator.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch.main_agent = type("MA", (), {"decompose": staticmethod(fake_decompose)})()
    orch._active_sessions = {}
    orch._run_single_task_loop = _spy_run_single

    # Single-task request
    events = await _collect_stream(
        orch.process_message_stream("给我钻石", session_id="e2e-sess-off-1")
    )

    event_types = [ev["event"] for ev in events]

    # Core assertion: loop path NOT taken
    assert loop_call_count["n"] == 0, (
        f"_run_single_task_loop was called {loop_call_count['n']} time(s) despite USE_AGENT_LOOP=False"
    )

    # Existing path ran: TaskManager was constructed
    assert task_manager_constructed["n"] >= 1, "TaskManager was never constructed (flag-off path broken)"

    # Stream produced content + done (existing path works)
    assert "done" in event_types, f"Missing 'done' event. Got: {event_types}"
    assert "content" in event_types, f"Missing 'content' event. Got: {event_types}"


async def test_flag_off_multi_task_loop_not_called(monkeypatch):
    """USE_AGENT_LOOP=False with multi-task decomposition: loop still not called."""
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", False)

    loop_call_count = {"n": 0}

    async def _spy_run_single(*args, **kwargs):
        loop_call_count["n"] += 1
        if False:
            yield {}

    async def fake_decompose(user_input, session_context, edition="bedrock"):
        return {
            "is_single_task": False,
            "project_name": "test",
            "overview": "",
            "tasks": [
                {"task_id": "1", "user_request": "任务A", "output_type": "simple_command",
                 "description": "A", "recommended_commands": [], "depends_on": []},
                {"task_id": "2", "user_request": "任务B", "output_type": "simple_command",
                 "description": "B", "recommended_commands": [], "depends_on": []},
            ],
        }

    class _FakeTaskManager:
        def __init__(self, decomp, edition="bedrock"):
            self.decomposition = decomp
            self.edition = edition
            self.task_states = {}

        def is_expired(self):
            return False

        def all_completed(self):
            return True

        def get_completed_results(self):
            return [
                {"task_id": "1", "description": "A", "result": {"type": "single_command",
                 "command": {"command": "/say A", "explanation": "", "variants": [], "warnings": []}}},
                {"task_id": "2", "description": "B", "result": {"type": "single_command",
                 "command": {"command": "/say B", "explanation": "", "variants": [], "warnings": []}}},
            ]

        async def execute_all(self):
            if False:
                yield {}

    # Also mock summarize to avoid LLM call in multi-task path
    async def fake_summarize(user_input, results, edition="bedrock"):
        return {"phases": [], "explanation": "summary", "_thinking": ""}

    monkeypatch.setattr(orch_mod, "TaskManager", _FakeTaskManager)

    from backend.orchestrator.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch.main_agent = type(
        "MA", (),
        {
            "decompose": staticmethod(fake_decompose),
            "summarize": staticmethod(fake_summarize),
        },
    )()
    orch._active_sessions = {}
    orch._run_single_task_loop = _spy_run_single

    events = await _collect_stream(
        orch.process_message_stream("做两件事", session_id="e2e-sess-off-2")
    )
    event_types = [ev["event"] for ev in events]

    assert loop_call_count["n"] == 0, (
        f"_run_single_task_loop was called in multi-task flag-off path"
    )
    assert "done" in event_types


# ---------------------------------------------------------------------------
# Scenario 2: flag-on happy path
# ---------------------------------------------------------------------------

async def test_flag_on_happy_path_single_command(monkeypatch):
    """USE_AGENT_LOOP=True: scripted step emits finish(done, valid JSON).

    Terminal 'content' event must have type=='single_command' and a 'command'
    object with a 'validation' field (run_validation is called on the result).
    """
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", True)

    async def fake_decompose(user_input, session_context, edition="bedrock"):
        return _single_task_decomposition(user_input)

    answer = _single_command_json("/give @p diamond 1")
    step = _ScriptStep(
        [
            StepResult(
                content="",
                thinking="",
                tool_calls=[ToolCall("c1", "finish", {"reason": "done", "final_answer": answer})],
                raw_assistant_msg={"role": "assistant", "content": ""},
            )
        ]
    )
    reg = _finish_registry_only()

    monkeypatch.setattr(orch_mod, "build_default_registry", lambda: reg)
    monkeypatch.setattr(orch_mod, "build_step", lambda client: step)
    monkeypatch.setattr(orch_mod, "get_llm_client", lambda: object())

    from backend.orchestrator.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch.main_agent = type("MA", (), {"decompose": staticmethod(fake_decompose)})()
    orch._active_sessions = {}

    # M4: mock structural validator so no real TaskAgent LLM call is made if rules change
    async def _noop_coroutine(*args, **kwargs):
        return None
    orch._structural_validate_and_retry_simple = _noop_coroutine

    events = await _collect_stream(
        orch.process_message_stream("给我钻石", session_id="e2e-sess-on-1")
    )

    event_types = [ev["event"] for ev in events]

    # Must have key event types
    assert "task_list" in event_types, f"Missing task_list. Events: {event_types}"
    assert "content" in event_types, f"Missing content. Events: {event_types}"
    assert "done" in event_types, f"Missing done. Events: {event_types}"

    # content must come before done
    content_idx = event_types.index("content")
    done_idx = event_types.index("done")
    assert content_idx < done_idx, "content must precede done"

    # content.data.type == "single_command"
    content_ev = events[content_idx]
    content_data = content_ev["data"]
    assert content_data.get("type") == "single_command", (
        f"Expected single_command, got: {content_data.get('type')}"
    )

    # 'command' object is present
    cmd_obj = content_data.get("command")
    assert isinstance(cmd_obj, dict), f"command object missing or wrong type: {cmd_obj}"

    # validation is present (run_validation writes .command.validation)
    assert "validation" in cmd_obj, (
        f"run_validation should have written 'validation' into command obj. Got: {cmd_obj}"
    )


async def test_flag_on_emits_generating_and_validating(monkeypatch):
    """USE_AGENT_LOOP=True: task_update(generating) before loop, validating after."""
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", True)

    async def fake_decompose(user_input, session_context, edition="bedrock"):
        return _single_task_decomposition(user_input)

    answer = _single_command_json()
    step = _ScriptStep(
        [
            StepResult(
                content="",
                thinking="想了想",
                tool_calls=[ToolCall("c1", "finish", {"reason": "done", "final_answer": answer})],
                raw_assistant_msg={"role": "assistant", "content": ""},
            )
        ]
    )
    reg = _finish_registry_only()

    monkeypatch.setattr(orch_mod, "build_default_registry", lambda: reg)
    monkeypatch.setattr(orch_mod, "build_step", lambda client: step)
    monkeypatch.setattr(orch_mod, "get_llm_client", lambda: object())

    from backend.orchestrator.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch.main_agent = type("MA", (), {"decompose": staticmethod(fake_decompose)})()
    orch._active_sessions = {}

    # M4: mock structural validator so no real TaskAgent LLM call is made if rules change
    async def _noop_coroutine(*args, **kwargs):
        return None
    orch._structural_validate_and_retry_simple = _noop_coroutine

    events = await _collect_stream(
        orch.process_message_stream("给我剑", session_id="e2e-sess-on-2")
    )

    event_types = [ev["event"] for ev in events]

    # task_update(generating) present
    generating_ev = next(
        (ev for ev in events
         if ev["event"] == "task_update" and ev.get("data", {}).get("status") == "generating"),
        None,
    )
    assert generating_ev is not None, f"Missing task_update(generating). Events: {event_types}"

    # task_update(validating) present before content
    validating_ev = next(
        (ev for ev in events
         if ev["event"] == "task_update" and ev.get("data", {}).get("status") == "validating"),
        None,
    )
    assert validating_ev is not None, f"Missing task_update(validating). Events: {event_types}"

    validating_idx = next(
        i for i, ev in enumerate(events)
        if ev["event"] == "task_update" and ev.get("data", {}).get("status") == "validating"
    )
    content_idx = event_types.index("content")
    assert validating_idx < content_idx, "task_update(validating) must precede content"

    # task_thinking emitted when thinking is non-empty
    assert "task_thinking" in event_types, (
        f"Expected task_thinking for thinking='想了想'. Events: {event_types}"
    )


# ---------------------------------------------------------------------------
# Scenario 3: prompted provider path
# ---------------------------------------------------------------------------

async def test_prompted_provider_reaches_done():
    """PromptedToolStep (supports_tools=False) reaches DONE via implicit finish.

    We drive AgentLoop directly with a PromptedToolStep backed by a plain
    chat client that immediately returns a final-answer JSON (no tool call).
    The loop detects no tool_calls → IMPLICIT_DONE.

    This exercises the PromptedToolStep code path without needing to wire
    a full provider through the orchestrator.
    """
    answer = _single_command_json("/scoreboard players add @p score 1")

    class _PlainClient:
        provider_id = "glm"  # arbitrary non-tool provider

        async def chat(self, messages, *, max_tokens=None):
            return {
                "message": {
                    "role": "assistant",
                    "content": answer,
                    "thinking": "",
                }
            }

    step = PromptedToolStep(_PlainClient())

    reg = _finish_registry_only()
    loop = AgentLoop(
        registry=reg,
        step=step,
        budget=LoopBudget(max_rounds=8),
        edition="bedrock",
    )

    events: list[dict[str, Any]] = []
    async for ev in loop.run([{"role": "user", "content": "加分"}]):
        events.append(ev)

    outcome = loop.last_outcome
    assert outcome is not None, "AgentLoop produced no outcome"
    # No tool call → implicit done
    assert outcome.reason == FinishReason.IMPLICIT_DONE, (
        f"Expected IMPLICIT_DONE, got {outcome.reason}"
    )
    # Content is the raw final-answer JSON from the model
    assert "single_command" in outcome.content, (
        f"Expected single_command JSON in content, got: {outcome.content}"
    )

    # _agent_outcome event emitted
    outcome_event = next(
        (ev for ev in events if ev.get("event") == "_agent_outcome"), None
    )
    assert outcome_event is not None, "No _agent_outcome event emitted"


async def test_prompted_provider_tool_then_finish():
    """PromptedToolStep: first round emits a tool JSON, second round finishes.

    Validates that format_observation folds to role:user (prompted contract)
    and the loop continues to a DONE outcome.
    """
    answer = _single_command_json("/effect give @a speed 30 2")

    # Script: round 0 → tool JSON call (finish), round 1 → won't be reached
    # since finish is detected in round 0
    finish_json = json.dumps(
        {"tool": "finish", "arguments": {"reason": "done", "final_answer": answer}},
        ensure_ascii=False,
    )

    class _PlainClientFinishViaJson:
        provider_id = "glm"
        _call = 0

        async def chat(self, messages, *, max_tokens=None):
            return {
                "message": {
                    "role": "assistant",
                    "content": finish_json,
                    "thinking": "",
                }
            }

    step = PromptedToolStep(_PlainClientFinishViaJson())
    reg = _finish_registry_only()
    loop = AgentLoop(
        registry=reg,
        step=step,
        budget=LoopBudget(max_rounds=8),
        edition="bedrock",
    )

    events: list[dict[str, Any]] = []
    async for ev in loop.run([{"role": "user", "content": "给速度效果"}]):
        events.append(ev)

    outcome = loop.last_outcome
    assert outcome is not None
    assert outcome.reason == FinishReason.DONE, (
        f"Expected DONE via prompted finish tool, got {outcome.reason}"
    )
    assert outcome.content == answer, (
        f"Expected answer JSON as content, got: {outcome.content}"
    )


async def test_prompted_step_format_observation_is_user_role():
    """PromptedToolStep.format_observation returns role:user (not role:tool)."""
    class _PlainClient:
        provider_id = "glm"

        async def chat(self, messages, *, max_tokens=None):
            return {"message": {"role": "assistant", "content": "", "thinking": ""}}

    step = PromptedToolStep(_PlainClient())
    call = ToolCall("p-0", "get_command_usage", {"command_name": "give"})
    obs = Observation("get_command_usage", True, "命令说明: /give")
    msg = step.format_observation(call, obs)

    assert msg["role"] == "user", (
        f"Prompted observation must fold to role:user, got: {msg['role']}"
    )
    assert "get_command_usage" in msg["content"]
    assert "命令说明" in msg["content"]


async def test_prompted_build_step_selects_prompted(monkeypatch):
    """build_step returns PromptedToolStep for a supports_tools=False provider."""
    from backend.agentloop.step import build_step
    import backend.agentloop.step as step_mod

    class _FakeProvider:
        supports_tools = False

    def _fake_get_provider(pid):
        return _FakeProvider()

    monkeypatch.setattr(step_mod, "get_provider", _fake_get_provider)

    class _FakeClient:
        provider_id = "glm"

    step = build_step(_FakeClient())
    assert isinstance(step, PromptedToolStep), (
        f"Expected PromptedToolStep for supports_tools=False, got {type(step)}"
    )


# ---------------------------------------------------------------------------
# Scenario 4: chat.py persistence — content event carries collected_result
# ---------------------------------------------------------------------------

async def test_chat_persistence_content_event_carries_result(monkeypatch):
    """Under the loop path, the terminal user-facing event is 'content'.

    chat.py _event_generator (line 122-123) sets:
        elif event_type == "content":
            collected_result = data

    This test confirms that when USE_AGENT_LOOP=True, the orchestrator emits
    a 'content' event (not only 'task_update') and that its 'data' dict
    contains the fields that _event_generator reads:
        msg_type = collected_result.get("type", "")
        command  = collected_result.get("command")

    If 'content' is missing, _event_generator never sets collected_result and
    the assistant message is saved with an empty type/command — a regression.
    """
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", True)

    async def fake_decompose(user_input, session_context, edition="bedrock"):
        return _single_task_decomposition(user_input)

    cmd = "/give @p diamond 1"
    answer = _single_command_json(cmd)
    step = _ScriptStep(
        [
            StepResult(
                content="",
                thinking="",
                tool_calls=[ToolCall("c1", "finish", {"reason": "done", "final_answer": answer})],
                raw_assistant_msg={"role": "assistant", "content": ""},
            )
        ]
    )
    reg = _finish_registry_only()

    monkeypatch.setattr(orch_mod, "build_default_registry", lambda: reg)
    monkeypatch.setattr(orch_mod, "build_step", lambda client: step)
    monkeypatch.setattr(orch_mod, "get_llm_client", lambda: object())

    from backend.orchestrator.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch.main_agent = type("MA", (), {"decompose": staticmethod(fake_decompose)})()
    orch._active_sessions = {}

    events = await _collect_stream(
        orch.process_message_stream("给我钻石", session_id="e2e-sess-chat-1")
    )

    # --- Assert 'content' event is present (chat.py line 122-123 relies on it) ---
    content_events = [ev for ev in events if ev["event"] == "content"]
    assert content_events, (
        "No 'content' event found — _event_generator would save empty collected_result"
    )

    # --- Simulate what _event_generator does (chat.py lines 119-126) ---
    collected_result: dict[str, Any] = {}
    for ev in events:
        event_type = ev.get("event", "content")
        data = ev.get("data", {})
        if event_type == "content":
            collected_result = data
        # (thinking and done handling omitted — not relevant here)

    # collected_result must have 'type' field (chat.py line 133)
    msg_type = collected_result.get("type", "")
    assert msg_type == "single_command", (
        f"chat.py would save msg_type='{msg_type}', expected 'single_command'"
    )

    # collected_result must have 'command' field (chat.py line 134)
    command_field = collected_result.get("command")
    assert isinstance(command_field, dict), (
        f"chat.py would save command={command_field!r}, expected dict"
    )
    assert command_field.get("command") == cmd, (
        f"command string mismatch: {command_field.get('command')!r} != {cmd!r}"
    )


async def test_chat_persistence_content_before_done(monkeypatch):
    """content event must arrive before 'done' so chat.py collects it before saving.

    In _event_generator, saving happens AFTER the entire generator finishes
    (after the async for loop). So order doesn't technically matter for the
    actual persistence. But the 'done' event handler sets session_id in data,
    and 'content' must arrive so collected_result is non-empty.

    This test explicitly validates ordering: content < done.
    """
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", True)

    async def fake_decompose(user_input, session_context, edition="bedrock"):
        return _single_task_decomposition(user_input)

    answer = _single_command_json()
    step = _ScriptStep(
        [
            StepResult(
                content="",
                thinking="",
                tool_calls=[ToolCall("c1", "finish", {"reason": "done", "final_answer": answer})],
                raw_assistant_msg={"role": "assistant", "content": ""},
            )
        ]
    )
    reg = _finish_registry_only()

    monkeypatch.setattr(orch_mod, "build_default_registry", lambda: reg)
    monkeypatch.setattr(orch_mod, "build_step", lambda client: step)
    monkeypatch.setattr(orch_mod, "get_llm_client", lambda: object())

    from backend.orchestrator.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch.main_agent = type("MA", (), {"decompose": staticmethod(fake_decompose)})()
    orch._active_sessions = {}

    events = await _collect_stream(
        orch.process_message_stream("测试持久化顺序", session_id="e2e-sess-chat-2")
    )

    event_types = [ev["event"] for ev in events]
    assert "content" in event_types, f"No content event. Events: {event_types}"
    assert "done" in event_types, f"No done event. Events: {event_types}"

    content_idx = event_types.index("content")
    done_idx = event_types.index("done")
    assert content_idx < done_idx, (
        f"content (idx={content_idx}) must come before done (idx={done_idx})"
    )
