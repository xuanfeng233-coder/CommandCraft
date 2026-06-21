"""Tests for BuildOrchestrator._execute_step_loop (Task 3: flag-on execution path).

Covers:
1. flag-on: status sequence reading→decomposing→executing→updating→complete (no reviewing/retrying).
2. flag-on: mgr.use_loop is True (seam activated).
3. flag-on: review_agent.review NOT called; write_agent.mark_step_done NOT called.
4. flag-on: after mark, reader_agent.parse_plan(written_md)[step_idx-1].status == "done".
5. flag-on: accumulated_context of step N is injected as session_context into step N+1's Planner.plan.
6. flag-off: review_agent.review IS called; write_agent.mark_step_done IS called.
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from backend.agents.planner_schemas import Decomposition, TaskDef
from backend.build.agents.reader_agent import reader_agent
from backend.build.build_orchestrator import BuildOrchestrator, BuildState, _regex_mark_step_done


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_decomp(n: int = 1) -> Decomposition:
    """Return a Decomposition with n tasks, valid graph."""
    tasks = [
        TaskDef(
            id=str(i),
            title=f"任务{i}标题",
            instruction=f"执行第{i}步操作",
            recommended_commands=["/say hi"],
        )
        for i in range(1, n + 1)
    ]
    return Decomposition(project_name="测试项目", overview="项目总览", tasks=tasks)


def _make_project_md(steps: int = 2) -> str:
    """Return a minimal PROJECT.md with N pending steps."""
    lines = ["# 测试项目", "", "## 概述", "测试用项目", ""]
    for i in range(1, steps + 1):
        lines += [
            f"## 步骤 {i}: 步骤{i}标题 [ ]",
            f"**需求**: 步骤{i}的需求",
            f"**实现思路**: 实现方法{i}",
            f"**涉及命令**: /say",
            f"- [ ] 子任务{i}",
            "",
        ]
    return "\n".join(lines)


async def _collect(gen) -> list[dict]:
    """Drain an async generator into a list of event dicts."""
    events = []
    async for ev in gen:
        events.append(ev)
    return events


def _make_stub_task_manager_cls(decomp: Decomposition):
    """Return a TaskManager class stub that records use_loop and yields no events."""

    class StubTaskManager:
        _instance = None

        def __init__(self, decomposition, edition="bedrock", use_loop=False):
            self.decomposition = decomposition
            self.edition = edition
            self.use_loop = use_loop
            StubTaskManager._instance = self

        async def execute_all(self):
            # Yield nothing — simulate an immediate empty execution
            return
            yield  # make it an async generator

        def get_completed_results(self):
            return []

    return StubTaskManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def orchestrator():
    return BuildOrchestrator()


@pytest.fixture()
def project_md_1step():
    return _make_project_md(1)


@pytest.fixture()
def project_md_2steps():
    return _make_project_md(2)


# ---------------------------------------------------------------------------
# Helpers to build a primed BuildState
# ---------------------------------------------------------------------------

def _prime_state(orchestrator: BuildOrchestrator, project_id: str, md: str) -> BuildState:
    """Register a BuildState in the orchestrator for the given project_id."""
    steps = reader_agent.parse_plan(md)
    state = BuildState(
        project_id=project_id,
        device_fp="fp-test",
        user_input="测试用户请求",
        edition="bedrock",
        status="executing",
        current_step=0,
        total_steps=len(steps),
        plan_content=md,
    )
    orchestrator._active_builds[project_id] = state
    return state


# ---------------------------------------------------------------------------
# 1 & 2 & 3: flag-on happy path — status sequence, use_loop, agents not called
# ---------------------------------------------------------------------------

async def test_flag_on_status_sequence_and_no_agents(orchestrator, project_md_1step):
    """flag-on: reading→decomposing→executing→updating→complete; no reviewing; use_loop True;
    review_agent.review and write_agent.mark_step_done NOT called."""

    project_id = "proj-loop-001"
    md = project_md_1step
    _prime_state(orchestrator, project_id, md)
    decomp = _make_decomp(1)

    StubTM = _make_stub_task_manager_cls(decomp)

    with (
        patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", True),
        patch.object(orchestrator.planner, "plan", new_callable=AsyncMock) as mock_plan,
        patch("backend.build.build_orchestrator.project_manager") as mock_pm,
        patch("backend.build.build_orchestrator.review_agent") as mock_review,
        patch("backend.build.build_orchestrator.write_agent") as mock_write,
        patch("backend.build.build_orchestrator.TaskManager", StubTM),
    ):
        mock_plan.return_value = (decomp, "thinking")
        mock_pm.read_project_md = AsyncMock(return_value=md)
        mock_pm.write_project_md = AsyncMock()

        events = await _collect(orchestrator._execute_step(project_id, 1))

    # Extract status sequence from build_step_update events
    statuses = [
        e["data"]["status"]
        for e in events
        if e["event"] == "build_step_update"
    ]

    assert statuses == ["reading", "decomposing", "executing", "updating", "complete"], (
        f"Expected reading→decomposing→executing→updating→complete, got: {statuses}"
    )

    # No reviewing in the sequence
    assert "reviewing" not in statuses
    assert "retrying" not in statuses

    # use_loop must be True on the stub instance
    assert StubTM._instance is not None
    assert StubTM._instance.use_loop is True

    # review_agent.review and write_agent.mark_step_done must NOT be called
    mock_review.review.assert_not_called()
    mock_write.mark_step_done.assert_not_called()


# ---------------------------------------------------------------------------
# 4: after mark, parse_plan(written_md)[step_idx-1].status == "done"
# ---------------------------------------------------------------------------

async def test_flag_on_regex_mark_makes_step_done(orchestrator, project_md_2steps):
    """flag-on: after _regex_mark_step_done, reader_agent.parse_plan reports status==done."""
    project_id = "proj-loop-002"
    md = project_md_2steps
    _prime_state(orchestrator, project_id, md)
    decomp = _make_decomp(1)

    StubTM = _make_stub_task_manager_cls(decomp)
    written_md: list[str] = []

    async def capture_write(pid, content):
        written_md.append(content)

    with (
        patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", True),
        patch.object(orchestrator.planner, "plan", new_callable=AsyncMock) as mock_plan,
        patch("backend.build.build_orchestrator.project_manager") as mock_pm,
        patch("backend.build.build_orchestrator.review_agent"),
        patch("backend.build.build_orchestrator.write_agent"),
        patch("backend.build.build_orchestrator.TaskManager", StubTM),
    ):
        mock_plan.return_value = (decomp, "")
        mock_pm.read_project_md = AsyncMock(return_value=md)
        mock_pm.write_project_md = AsyncMock(side_effect=capture_write)

        await _collect(orchestrator._execute_step(project_id, 1))

    # write_project_md must have been called with some content
    assert written_md, "write_project_md was never called"
    saved = written_md[-1]

    # Re-parse the saved markdown and check step 1 is done
    steps = reader_agent.parse_plan(saved)
    step1 = next((s for s in steps if s.index == 1), None)
    assert step1 is not None, "Step 1 not found in written markdown"
    assert step1.status == "done", (
        f"Expected step 1 status 'done', got '{step1.status}' in:\n{saved}"
    )

    # Step 2 should remain pending
    step2 = next((s for s in steps if s.index == 2), None)
    assert step2 is not None
    assert step2.status == "pending", (
        f"Step 2 should still be pending, got '{step2.status}'"
    )


# ---------------------------------------------------------------------------
# 5: accumulated_context of step N injected into step N+1's Planner.plan
# ---------------------------------------------------------------------------

async def test_flag_on_accumulated_context_chaining(orchestrator, project_md_2steps):
    """flag-on: accumulated_context from step 1 is passed as session_context to step 2."""
    project_id = "proj-loop-003"
    md = project_md_2steps
    state = _prime_state(orchestrator, project_id, md)
    decomp = _make_decomp(1)

    StubTM = _make_stub_task_manager_cls(decomp)
    plan_calls: list[dict] = []

    async def capture_plan(user_input, session_context="", **kwargs):
        plan_calls.append({"user_input": user_input, "session_context": session_context})
        return (decomp, "")

    with (
        patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", True),
        patch.object(orchestrator.planner, "plan", side_effect=capture_plan),
        patch("backend.build.build_orchestrator.project_manager") as mock_pm,
        patch("backend.build.build_orchestrator.review_agent"),
        patch("backend.build.build_orchestrator.write_agent"),
        patch("backend.build.build_orchestrator.TaskManager", StubTM),
    ):
        mock_pm.read_project_md = AsyncMock(return_value=md)
        mock_pm.write_project_md = AsyncMock()

        # Execute step 1
        await _collect(orchestrator._execute_step(project_id, 1))

        # After step 1, accumulated_context should be non-empty
        ctx_after_step1 = state.accumulated_context

        # Execute step 2
        await _collect(orchestrator._execute_step(project_id, 2))

    assert len(plan_calls) == 2, f"Expected 2 Planner.plan calls, got {len(plan_calls)}"

    # Step 1 plan call: session_context may contain project overview but NOT step1 artifacts
    # Step 2 plan call: session_context MUST contain step1's accumulated_context
    step2_ctx = plan_calls[1]["session_context"]
    assert ctx_after_step1 != "", "accumulated_context should be set after step 1"
    assert ctx_after_step1 in step2_ctx, (
        f"Step 1 accumulated_context not found in step 2 session_context.\n"
        f"accumulated_context: {ctx_after_step1!r}\n"
        f"step2 session_context: {step2_ctx!r}"
    )


# ---------------------------------------------------------------------------
# 6: flag-off regression — review_agent and write_agent ARE called
# ---------------------------------------------------------------------------

async def test_flag_off_calls_review_and_write_agent(orchestrator, project_md_1step):
    """flag-off: review_agent.review and write_agent.mark_step_done ARE called."""
    from backend.build.agents.review_agent import ReviewResult

    project_id = "proj-loop-004"
    md = project_md_1step
    _prime_state(orchestrator, project_id, md)

    review_result = ReviewResult(complete=True, missing_items=[])

    # Stub TaskManager that does nothing and returns empty results
    class FlagOffStubTM:
        def __init__(self, decomposition, edition="bedrock", use_loop=False):
            self.decomposition = decomposition
            self.edition = edition
            self.use_loop = use_loop

        async def execute_all(self):
            return
            yield  # async generator

        def get_completed_results(self):
            return []

    with (
        patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", False),
        patch("backend.build.build_orchestrator.project_manager") as mock_pm,
        patch("backend.build.build_orchestrator.review_agent") as mock_review,
        patch("backend.build.build_orchestrator.write_agent") as mock_write,
        patch("backend.build.build_orchestrator.TaskManager", FlagOffStubTM),
        patch.object(
            orchestrator.main_agent,
            "decompose",
            new_callable=AsyncMock,
        ) as mock_decompose,
    ):
        mock_decompose.return_value = {
            "tasks": [
                {
                    "task_id": "1",
                    "description": "测试任务",
                    "depends_on": [],
                }
            ]
        }
        mock_review.review = AsyncMock(return_value=review_result)
        mock_write.mark_step_done = AsyncMock(return_value=md)
        mock_pm.read_project_md = AsyncMock(return_value=md)
        mock_pm.write_project_md = AsyncMock()

        events = await _collect(orchestrator._execute_step(project_id, 1))

    # review_agent.review must have been called
    mock_review.review.assert_called_once()

    # write_agent.mark_step_done must have been called
    mock_write.mark_step_done.assert_called_once()

    # Status sequence must include "reviewing"
    statuses = [
        e["data"]["status"]
        for e in events
        if e["event"] == "build_step_update"
    ]
    assert "reviewing" in statuses, f"Expected 'reviewing' in flag-off statuses: {statuses}"


# ---------------------------------------------------------------------------
# Unit test for _regex_mark_step_done standalone
# ---------------------------------------------------------------------------

def test_regex_mark_step_done_marks_header_and_subtasks():
    """_regex_mark_step_done correctly updates header, subtasks, and appends result."""
    md = _make_project_md(2)
    result = _regex_mark_step_done(md, 1, "生成了3条命令")

    steps = reader_agent.parse_plan(result)
    step1 = next(s for s in steps if s.index == 1)
    step2 = next(s for s in steps if s.index == 2)

    assert step1.status == "done"
    assert all(st.done for st in step1.subtasks), "All subtasks of step 1 should be done"
    assert step2.status == "pending", "Step 2 should remain pending"
    assert "生成了3条命令" in result, "Summary should appear in result"
    assert "**执行结果**" in result


def test_regex_mark_step_done_does_not_touch_other_steps():
    """_regex_mark_step_done only changes the target step."""
    md = _make_project_md(3)
    result = _regex_mark_step_done(md, 2, "步骤2完成")

    steps = reader_agent.parse_plan(result)
    assert steps[0].status == "pending"  # step 1 untouched
    assert steps[1].status == "done"     # step 2 marked done
    assert steps[2].status == "pending"  # step 3 untouched
