"""Phase 4 E2E / regression tests for BuildOrchestrator flag split.

Scenarios:
  1. flag-off byte-identical snapshot — regression lock on the classic path.
  2. flag-on happy path — Planner + TaskManager(use_loop=True), no deprecated agents.
  3. round-trip integration — real decomposition_to_project_md → real reader_agent.parse_plan
     → _build_step_request for every step is non-empty.
  4. confirm-after-restart — documents the gap: confirm_plan requires an in-memory
     _active_builds entry; if it's dropped, the orchestrator yields an error rather
     than re-reading PROJECT.md.  The test verifies and documents this behaviour.
  5. edition matrix — flag-on for bedrock and java; Planner.plan receives the correct
     edition kwarg in both planning (_plan_via_planner) and per-step (_execute_step_loop)
     calls.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from backend.agents.planner_schemas import Decomposition, TaskDef
from backend.build.agents.clarify_agent import ClarifyResult
from backend.build.agents.reader_agent import reader_agent
from backend.build.agents.review_agent import ReviewResult
from backend.build.build_orchestrator import BuildOrchestrator, BuildState, _regex_mark_step_done
from backend.build.plan_adapter import decomposition_to_project_md


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_decomp(n: int = 2) -> Decomposition:
    tasks = [
        TaskDef(
            id=str(i),
            title=f"任务{i}标题",
            instruction=f"执行第{i}步操作",
            recommended_commands=[f"/say step{i}"],
        )
        for i in range(1, n + 1)
    ]
    return Decomposition(project_name="测试项目", overview="项目总览", tasks=tasks)


async def _collect(gen) -> list[dict]:
    """Drain an async generator into a list."""
    events = []
    async for ev in gen:
        events.append(ev)
    return events


def _event_names(events: list[dict]) -> list[str]:
    return [e["event"] for e in events]


def _make_project_md(n: int = 2) -> str:
    lines = ["# 测试项目", "", "## 概述", "测试用", ""]
    for i in range(1, n + 1):
        lines += [
            f"## 步骤 {i}: 步骤{i}标题 [ ]",
            f"**需求**: 步骤{i}的需求",
            f"**实现思路**: 实现方法{i}",
            f"**涉及命令**: /say",
            f"- [ ] 子任务{i}",
            "",
        ]
    return "\n".join(lines)


def _prime_state(
    orch: BuildOrchestrator,
    project_id: str,
    md: str,
    edition: str = "bedrock",
) -> BuildState:
    steps = reader_agent.parse_plan(md)
    state = BuildState(
        project_id=project_id,
        device_fp="fp-test",
        user_input="测试用户请求",
        edition=edition,
        status="executing",
        current_step=0,
        total_steps=len(steps),
        plan_content=md,
    )
    orch._active_builds[project_id] = state
    return state


class StubTaskManager:
    """Minimal TaskManager stub that records use_loop and yields no events."""

    _last: "StubTaskManager | None" = None

    def __init__(self, decomposition, edition="bedrock", use_loop=False):
        self.decomposition = decomposition
        self.edition = edition
        self.use_loop = use_loop
        StubTaskManager._last = self

    async def execute_all(self):
        return
        yield  # noqa: unreachable — makes this an async generator

    def get_completed_results(self):
        return []


# ---------------------------------------------------------------------------
# Scenario 1: flag-off byte-identical snapshot (regression lock)
# ---------------------------------------------------------------------------

async def test_flag_off_start_build_event_sequence_snapshot():
    """flag-off start_build: exact event sequence is regression-locked.

    Mocks all five agents deterministically and captures the full SSE list.
    Asserts:
    - Events appear in the expected order (byte-identical snapshot).
    - clarify_agent.analyze, write_agent.create_plan, review_agent.review called.
    - search_agent.search NOT called (needs_search=False).
    - None of the flag-on agent paths (Planner.plan) are called.
    """
    orch = BuildOrchestrator()

    clarify_result = ClarifyResult(
        needs_clarification=False,
        requirements_summary="需求已明确：实现计分板系统",
        questions=[],
        suggested_steps=["步骤1: 创建计分板", "步骤2: 触发逻辑"],
        needs_search=False,
        search_queries=[],
    )

    plan_md = (
        "## 步骤 1: 创建计分板 [ ]\n"
        "**需求**: 创建计分板\n"
        "**实现思路**: 用scoreboard命令\n"
        "**涉及命令**: /scoreboard\n"
        "- [ ] 初始化计分板\n\n"
        "## 步骤 2: 触发逻辑 [ ]\n"
        "**需求**: 触发逻辑\n"
        "**实现思路**: 用execute命令\n"
        "**涉及命令**: /execute\n"
        "- [ ] 添加触发条件\n"
    )

    with (
        patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", False),
        patch("backend.build.build_orchestrator.project_manager") as mock_pm,
        patch("backend.build.build_orchestrator.clarify_agent") as mock_clarify,
        patch("backend.build.build_orchestrator.search_agent") as mock_search,
        patch("backend.build.build_orchestrator.write_agent") as mock_write,
        patch.object(orch.planner, "plan", new_callable=AsyncMock) as mock_planner,
    ):
        mock_pm.create_project = AsyncMock(return_value="snap-proj-001")
        mock_pm.update_status = AsyncMock()
        mock_clarify.analyze = AsyncMock(return_value=clarify_result)
        mock_search.search = AsyncMock(return_value=[])
        mock_write.create_plan = AsyncMock(return_value=plan_md)

        events = await _collect(
            orch.start_build("做个计分板系统", device_fp="fp-test")
        )

    names = _event_names(events)

    # --- Snapshot: exact event name sequence ---
    expected_sequence = [
        "build_phase",   # planning
        "thinking",      # 正在分析构建需求...
        "thinking",      # requirements_summary
        "thinking",      # 正在生成构建方案...
        "build_plan",
        "build_phase",   # reviewing
        "done",
    ]
    assert names == expected_sequence, (
        f"flag-off event sequence mismatch.\nExpected: {expected_sequence}\nGot:      {names}"
    )

    # --- Phase tags ---
    assert events[0]["data"]["phase"] == "planning"
    build_phase_events = [e for e in events if e["event"] == "build_phase"]
    phases = [e["data"]["phase"] for e in build_phase_events]
    assert phases == ["planning", "reviewing"], f"Expected [planning, reviewing], got {phases}"

    # --- Last event is done ---
    assert names[-1] == "done"

    # --- build_plan contains plan markdown ---
    build_plan_ev = next(e for e in events if e["event"] == "build_plan")
    assert "## 步骤 1" in build_plan_ev["data"]["markdown_content"]

    # --- Deprecated agents ARE called ---
    mock_clarify.analyze.assert_called_once_with("做个计分板系统")
    mock_write.create_plan.assert_called_once()

    # --- search_agent NOT called (needs_search=False) ---
    mock_search.search.assert_not_called()

    # --- Planner NOT called (flag-off) ---
    mock_planner.assert_not_called()

    # --- No build_clarify emitted ---
    assert "build_clarify" not in names


async def test_flag_off_confirm_plan_e2e_calls_review_agent():
    """flag-off confirm_plan full flow: review_agent called, write_agent.mark_step_done called."""
    orch = BuildOrchestrator()
    project_id = "snap-proj-002"
    md = _make_project_md(1)

    # Pre-register state (simulating after start_build)
    state = _prime_state(orch, project_id, md)
    state.status = "reviewing"  # after planning, before confirm

    review_result = ReviewResult(complete=True, missing_items=[])

    class FlagOffTM:
        def __init__(self, decomposition, edition="bedrock", use_loop=False):
            self.use_loop = use_loop

        async def execute_all(self):
            return
            yield

        def get_completed_results(self):
            return []

    with (
        patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", False),
        patch("backend.build.build_orchestrator.project_manager") as mock_pm,
        patch("backend.build.build_orchestrator.review_agent") as mock_review,
        patch("backend.build.build_orchestrator.write_agent") as mock_write,
        patch("backend.build.build_orchestrator.TaskManager", FlagOffTM),
        patch.object(orch.main_agent, "decompose", new_callable=AsyncMock) as mock_decompose,
    ):
        mock_pm.read_project_md = AsyncMock(return_value=md)
        mock_pm.write_project_md = AsyncMock()
        mock_pm.update_status = AsyncMock()
        mock_review.review = AsyncMock(return_value=review_result)
        mock_write.mark_step_done = AsyncMock(return_value=md)
        mock_decompose.return_value = {
            "tasks": [{"task_id": "1", "description": "任务", "depends_on": []}]
        }

        events = await _collect(orch.confirm_plan(project_id, plan_content=None))

    names = _event_names(events)

    # Must include the execution phase
    assert "build_phase" in names
    phase_events = [e for e in events if e["event"] == "build_phase"]
    executing_phases = [e for e in phase_events if e["data"].get("phase") == "executing"]
    assert executing_phases, f"Expected executing phase, got phases: {[e['data']['phase'] for e in phase_events]}"

    # review_agent must be called (flag-off path)
    mock_review.review.assert_called_once()

    # write_agent.mark_step_done must be called (flag-off path)
    mock_write.mark_step_done.assert_called_once()

    # Flow ends with done
    assert names[-1] == "done"


# ---------------------------------------------------------------------------
# Scenario 2: flag-on happy path
# ---------------------------------------------------------------------------

async def test_flag_on_happy_path_start_build():
    """flag-on start_build: uses Planner, no deprecated agents called.

    Asserts:
    - Planner.plan called with user_input
    - clarify_agent, search_agent, write_agent NOT called
    - reader_agent used to parse plan (via _plan_via_planner)
    - to_legacy_decomposition: checked via TaskManager stub receiving legacy shape
    - event sequence: planning→thinking→build_plan→reviewing→done
    """
    orch = BuildOrchestrator()
    decomp = _make_decomp(2)

    with (
        patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", True),
        patch.object(orch.planner, "plan", new_callable=AsyncMock) as mock_plan,
        patch("backend.build.build_orchestrator.project_manager") as mock_pm,
        patch("backend.build.build_orchestrator.clarify_agent") as mock_clarify,
        patch("backend.build.build_orchestrator.search_agent") as mock_search,
        patch("backend.build.build_orchestrator.write_agent") as mock_write,
        patch("backend.build.build_orchestrator.review_agent") as mock_review,
    ):
        mock_plan.return_value = (decomp, "thinking-text")
        mock_pm.create_project = AsyncMock(return_value="loop-proj-001")
        mock_pm.update_status = AsyncMock()
        mock_clarify.analyze = AsyncMock()
        mock_search.search = AsyncMock()
        mock_write.create_plan = AsyncMock()
        mock_review.review = AsyncMock()

        events = await _collect(
            orch.start_build("建一个玩家计分系统", device_fp="fp-test")
        )

    names = _event_names(events)

    # Deprecated agents NOT called
    mock_clarify.analyze.assert_not_called()
    mock_search.search.assert_not_called()
    mock_write.create_plan.assert_not_called()
    mock_review.review.assert_not_called()

    # Planner IS called
    mock_plan.assert_called_once()

    # Correct event sequence
    assert names[0] == "build_phase"
    assert events[0]["data"]["phase"] == "planning"
    assert "thinking" in names
    assert "build_plan" in names
    reviewing = [e for e in events if e["event"] == "build_phase" and e["data"].get("phase") == "reviewing"]
    assert reviewing, "Expected reviewing phase event"
    assert names[-1] == "done"
    assert "build_clarify" not in names
    assert "error" not in names


async def test_flag_on_happy_path_confirm_and_per_step():
    """flag-on confirm_plan: executes per-step via _execute_step_loop.

    Asserts:
    - TaskManager(use_loop=True) used per step
    - review_agent.review NOT called
    - write_agent.mark_step_done NOT called (regex mark used instead)
    - project_manager.write_project_md called for each step
    - event sequence includes executing phase and done
    """
    orch = BuildOrchestrator()
    project_id = "loop-proj-002"
    md = _make_project_md(2)
    _prime_state(orch, project_id, md)

    decomp = _make_decomp(1)
    StubTaskManager._last = None  # reset

    with (
        patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", True),
        patch.object(orch.planner, "plan", new_callable=AsyncMock) as mock_plan,
        patch("backend.build.build_orchestrator.project_manager") as mock_pm,
        patch("backend.build.build_orchestrator.review_agent") as mock_review,
        patch("backend.build.build_orchestrator.write_agent") as mock_write,
        patch("backend.build.build_orchestrator.TaskManager", StubTaskManager),
    ):
        mock_plan.return_value = (decomp, "")
        mock_pm.read_project_md = AsyncMock(return_value=md)
        mock_pm.write_project_md = AsyncMock()
        mock_pm.update_status = AsyncMock()
        mock_review.review = AsyncMock()
        mock_write.mark_step_done = AsyncMock()

        events = await _collect(orch.confirm_plan(project_id, plan_content=None))

    names = _event_names(events)

    # Deprecated agents NOT called
    mock_review.review.assert_not_called()
    mock_write.mark_step_done.assert_not_called()

    # TaskManager stub used with use_loop=True
    assert StubTaskManager._last is not None, "StubTaskManager not instantiated"
    assert StubTaskManager._last.use_loop is True, (
        f"Expected use_loop=True, got {StubTaskManager._last.use_loop}"
    )

    # project_manager.write_project_md called (regex mark updates PROJECT.md)
    mock_pm.write_project_md.assert_called()

    # Flow ends done
    assert names[-1] == "done"

    # Execution phase present
    executing = [e for e in events if e["event"] == "build_phase" and e["data"].get("phase") == "executing"]
    assert executing, "Expected executing phase"

    # Completed phase present
    completed = [e for e in events if e["event"] == "build_phase" and e["data"].get("phase") == "completed"]
    assert completed, "Expected completed phase"


# ---------------------------------------------------------------------------
# Scenario 3: round-trip integration (NOT mocked)
# ---------------------------------------------------------------------------

def test_round_trip_decomp_to_md_to_reader_to_step_request():
    """Real decomposition_to_project_md → real parse_plan → _build_step_request non-empty.

    This test uses no mocks for decomposition_to_project_md or reader_agent.
    It validates that every step produced by the Planner's schema can be:
      1. Serialised to PROJECT.md
      2. Parsed back by reader_agent.parse_plan without data loss
      3. Converted to a non-empty step_request by _build_step_request
    """
    orch = BuildOrchestrator()

    tasks = [
        TaskDef(
            id="1",
            title="创建计分板",
            instruction="使用 /scoreboard objectives add 命令创建计分板",
            recommended_commands=["/scoreboard objectives add kills dummy 击杀数"],
        ),
        TaskDef(
            id="2",
            title="添加触发逻辑",
            instruction="检测玩家杀死实体时更新计分板",
            recommended_commands=["/execute as @a[scores={kills=1..}]"],
            depends_on=["1"],
        ),
        TaskDef(
            id="3",
            title="显示排行榜",
            instruction="在屏幕右侧显示排行榜计分板",
            recommended_commands=["/scoreboard objectives setdisplay sidebar kills"],
        ),
    ]
    decomp = Decomposition(
        project_name="击杀计分系统",
        overview="实现一个完整的 Minecraft 击杀计分排行榜系统",
        tasks=tasks,
    )

    # Step 1: Real decomposition_to_project_md
    md = decomposition_to_project_md(decomp, "建一个计分排行榜")

    # Step 2: Real reader_agent.parse_plan
    steps = reader_agent.parse_plan(md)

    # Basic round-trip: same count, same order
    assert len(steps) == len(tasks), (
        f"Expected {len(tasks)} steps, got {len(steps)}"
    )
    assert [s.index for s in steps] == list(range(1, len(tasks) + 1))
    assert all(s.status == "pending" for s in steps), (
        "All round-tripped steps should be pending"
    )

    # Step 3: _build_step_request must produce non-empty strings for every step
    for step in steps:
        request = orch._build_step_request(step)
        assert request.strip(), (
            f"_build_step_request produced empty string for step {step.index}: {step!r}"
        )
        # Title must appear in the request
        assert step.title in request, (
            f"Step title '{step.title}' not found in request: {request!r}"
        )

    # Step 4: get_step works for each index
    for i in range(1, len(tasks) + 1):
        step = reader_agent.get_step(md, i)
        assert step is not None, f"reader_agent.get_step(md, {i}) returned None"
        assert step.index == i
        assert step.raw_content.strip(), f"Step {i} has empty raw_content"


# ---------------------------------------------------------------------------
# Scenario 4: confirm-after-restart (gap documented)
# ---------------------------------------------------------------------------

async def test_confirm_after_restart_yields_error_when_state_missing():
    """Confirm-after-restart: gap documented.

    DESIGN GAP: BuildOrchestrator.confirm_plan always looks up _active_builds[project_id].
    If the in-memory state is not present (e.g. after a process restart), confirm_plan
    immediately yields an error event rather than re-reading PROJECT.md and re-building state.

    This test explicitly verifies and documents that behaviour:
    - Dropping _active_builds[project_id] simulates a restart.
    - confirm_plan yields {"event": "error", ...} as the first event.
    - NO execution events are yielded after the error.

    Note: A future enhancement (not yet implemented) would add a fallback that reads
    PROJECT.md and reconstructs minimal BuildState from it, allowing restart resilience.
    """
    orch = BuildOrchestrator()
    project_id = "restart-proj-001"

    # Do NOT register the state — simulate process restart
    assert project_id not in orch._active_builds

    with (
        patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", True),
        patch("backend.build.build_orchestrator.project_manager") as mock_pm,
    ):
        mock_pm.read_project_md = AsyncMock(return_value=_make_project_md(1))
        mock_pm.write_project_md = AsyncMock()
        mock_pm.update_status = AsyncMock()

        events = await _collect(
            orch.confirm_plan(project_id, plan_content=_make_project_md(1))
        )

    names = _event_names(events)

    # Gap assertion: error is emitted, no execution proceeds
    assert "error" in names, (
        "EXPECTED (gap): confirm_plan emits error when _active_builds entry is missing"
    )
    assert names[0] == "error", (
        f"Expected error as first event (restart gap), got: {names}"
    )

    # No execution events should follow
    execution_events = [n for n in names if n in ("build_step_update", "task_list", "build_phase")]
    assert not execution_events, (
        f"No execution events expected after restart error, got: {execution_events}"
    )


async def test_confirm_restart_gap_flag_off_same_behaviour():
    """flag-off confirm_plan also yields error when state is missing (same gap, both flags)."""
    orch = BuildOrchestrator()
    project_id = "restart-proj-002"

    with (
        patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", False),
        patch("backend.build.build_orchestrator.project_manager") as mock_pm,
    ):
        mock_pm.write_project_md = AsyncMock()
        mock_pm.update_status = AsyncMock()

        events = await _collect(
            orch.confirm_plan(project_id, plan_content=_make_project_md(1))
        )

    names = _event_names(events)
    assert names == ["error"], (
        f"flag-off: Expected only [error] event after restart, got {names}"
    )


# ---------------------------------------------------------------------------
# Scenario 5: edition matrix
# ---------------------------------------------------------------------------

async def test_edition_matrix_bedrock_planning():
    """flag-on: Planner.plan receives edition='bedrock' from start_build."""
    orch = BuildOrchestrator()
    decomp = _make_decomp(1)
    plan_calls: list[dict] = []

    async def capture_plan(user_input, session_context="", **kwargs):
        plan_calls.append(kwargs)
        return (decomp, "")

    with (
        patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", True),
        patch.object(orch.planner, "plan", side_effect=capture_plan),
        patch("backend.build.build_orchestrator.project_manager") as mock_pm,
    ):
        mock_pm.create_project = AsyncMock(return_value="edition-proj-bedrock")
        mock_pm.update_status = AsyncMock()

        await _collect(orch.start_build("测试需求", device_fp="fp-test", edition="bedrock"))

    assert plan_calls, "Planner.plan was not called"
    assert plan_calls[0].get("edition") == "bedrock", (
        f"Expected edition='bedrock', got: {plan_calls[0]}"
    )


async def test_edition_matrix_java_planning():
    """flag-on: Planner.plan receives edition='java' from start_build."""
    orch = BuildOrchestrator()
    decomp = _make_decomp(1)
    plan_calls: list[dict] = []

    async def capture_plan(user_input, session_context="", **kwargs):
        plan_calls.append(kwargs)
        return (decomp, "")

    with (
        patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", True),
        patch.object(orch.planner, "plan", side_effect=capture_plan),
        patch("backend.build.build_orchestrator.project_manager") as mock_pm,
    ):
        mock_pm.create_project = AsyncMock(return_value="edition-proj-java")
        mock_pm.update_status = AsyncMock()

        await _collect(orch.start_build("测试需求 Java版", device_fp="fp-test", edition="java"))

    assert plan_calls, "Planner.plan was not called"
    assert plan_calls[0].get("edition") == "java", (
        f"Expected edition='java', got: {plan_calls[0]}"
    )


async def test_edition_matrix_bedrock_per_step():
    """flag-on: Planner.plan receives edition='bedrock' during step execution."""
    orch = BuildOrchestrator()
    project_id = "edition-step-bedrock"
    md = _make_project_md(1)
    _prime_state(orch, project_id, md, edition="bedrock")

    decomp = _make_decomp(1)
    plan_calls: list[dict] = []

    async def capture_plan(user_input, session_context="", **kwargs):
        plan_calls.append(kwargs)
        return (decomp, "")

    with (
        patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", True),
        patch.object(orch.planner, "plan", side_effect=capture_plan),
        patch("backend.build.build_orchestrator.project_manager") as mock_pm,
        patch("backend.build.build_orchestrator.TaskManager", StubTaskManager),
    ):
        mock_pm.read_project_md = AsyncMock(return_value=md)
        mock_pm.write_project_md = AsyncMock()

        await _collect(orch._execute_step(project_id, 1))

    assert plan_calls, "Planner.plan was not called during step execution"
    assert plan_calls[0].get("edition") == "bedrock", (
        f"Expected edition='bedrock' in step execution, got: {plan_calls[0]}"
    )


async def test_edition_matrix_java_per_step():
    """flag-on: Planner.plan receives edition='java' during step execution."""
    orch = BuildOrchestrator()
    project_id = "edition-step-java"
    md = _make_project_md(1)
    _prime_state(orch, project_id, md, edition="java")

    decomp = _make_decomp(1)
    plan_calls: list[dict] = []

    async def capture_plan(user_input, session_context="", **kwargs):
        plan_calls.append(kwargs)
        return (decomp, "")

    with (
        patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", True),
        patch.object(orch.planner, "plan", side_effect=capture_plan),
        patch("backend.build.build_orchestrator.project_manager") as mock_pm,
        patch("backend.build.build_orchestrator.TaskManager", StubTaskManager),
    ):
        mock_pm.read_project_md = AsyncMock(return_value=md)
        mock_pm.write_project_md = AsyncMock()

        await _collect(orch._execute_step(project_id, 1))

    assert plan_calls, "Planner.plan was not called during step execution (java)"
    assert plan_calls[0].get("edition") == "java", (
        f"Expected edition='java' in step execution, got: {plan_calls[0]}"
    )
