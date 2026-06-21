"""Tests for Task 4: BUILD_LOOP_REVIEW completeness check sub-flag.

Covers:
1. BUILD_LOOP_REVIEW=False (default): no 'reviewing' event, exactly one TaskManager pass.
2. BUILD_LOOP_REVIEW=True + mocked completeness check returns complete: emits 'reviewing', no retry.
3. BUILD_LOOP_REVIEW=True + returns missing: one retry with missing appended, capped at BUILD_MAX_REVIEW_RETRIES.
4. old review_agent.review never called regardless of BUILD_LOOP_REVIEW (flag-on).
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from backend.agents.planner_schemas import Decomposition, TaskDef
from backend.build.agents.reader_agent import reader_agent
from backend.build.build_orchestrator import BuildOrchestrator, BuildState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_decomp(n: int = 1) -> Decomposition:
    """Return a Decomposition with n tasks."""
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


def _make_project_md(steps: int = 1) -> str:
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


class StubTaskManager:
    """Minimal TaskManager stub that records call count and yields nothing."""

    call_count = 0
    instances: list["StubTaskManager"] = []

    def __init__(self, decomposition, edition="bedrock", use_loop=False):
        self.decomposition = decomposition
        self.edition = edition
        self.use_loop = use_loop
        StubTaskManager.instances.append(self)
        StubTaskManager.call_count += 1

    async def execute_all(self):
        return
        yield  # make it an async generator

    def get_completed_results(self):
        return []

    @classmethod
    def reset(cls):
        cls.call_count = 0
        cls.instances = []


def _prime_state(orchestrator: BuildOrchestrator, project_id: str, md: str) -> BuildState:
    """Register a BuildState for the given project_id."""
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
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_stub():
    StubTaskManager.reset()
    yield


@pytest.fixture()
def orchestrator():
    return BuildOrchestrator()


@pytest.fixture()
def project_md():
    return _make_project_md(1)


# ---------------------------------------------------------------------------
# Test 1: BUILD_LOOP_REVIEW=False (default) — no reviewing, exactly one pass
# ---------------------------------------------------------------------------

async def test_loop_review_false_no_reviewing_event_one_pass(orchestrator, project_md):
    """BUILD_LOOP_REVIEW=False: no 'reviewing' event and exactly one TaskManager pass."""
    project_id = "proj-cr-001"
    md = project_md
    _prime_state(orchestrator, project_id, md)
    decomp = _make_decomp(1)

    with (
        patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", True),
        patch("backend.build.build_orchestrator.BUILD_LOOP_REVIEW", False),
        patch.object(orchestrator.planner, "plan", new_callable=AsyncMock) as mock_plan,
        patch("backend.build.build_orchestrator.project_manager") as mock_pm,
        patch("backend.build.build_orchestrator.review_agent") as mock_review,
        patch("backend.build.build_orchestrator.write_agent"),
        patch("backend.build.build_orchestrator.TaskManager", StubTaskManager),
    ):
        mock_plan.return_value = (decomp, "thinking")
        mock_pm.read_project_md = AsyncMock(return_value=md)
        mock_pm.write_project_md = AsyncMock()

        events = await _collect(orchestrator._execute_step(project_id, 1))

    statuses = [
        e["data"]["status"]
        for e in events
        if e["event"] == "build_step_update"
    ]

    # No reviewing event
    assert "reviewing" not in statuses, (
        f"Expected no 'reviewing' with BUILD_LOOP_REVIEW=False, got: {statuses}"
    )

    # Exactly one TaskManager pass
    assert StubTaskManager.call_count == 1, (
        f"Expected exactly 1 TaskManager pass, got {StubTaskManager.call_count}"
    )

    # review_agent.review must NOT be called (flag-on path skips old review_agent)
    mock_review.review.assert_not_called()


# ---------------------------------------------------------------------------
# Test 2: BUILD_LOOP_REVIEW=True + completeness check returns complete
#         → emits 'reviewing', no retry (single TaskManager pass)
# ---------------------------------------------------------------------------

async def test_loop_review_true_complete_no_retry(orchestrator, project_md):
    """BUILD_LOOP_REVIEW=True + complete: emits 'reviewing', no retry."""
    project_id = "proj-cr-002"
    md = project_md
    _prime_state(orchestrator, project_id, md)
    decomp = _make_decomp(1)

    with (
        patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", True),
        patch("backend.build.build_orchestrator.BUILD_LOOP_REVIEW", True),
        patch.object(orchestrator.planner, "plan", new_callable=AsyncMock) as mock_plan,
        patch("backend.build.build_orchestrator.project_manager") as mock_pm,
        patch("backend.build.build_orchestrator.review_agent") as mock_review,
        patch("backend.build.build_orchestrator.write_agent"),
        patch("backend.build.build_orchestrator.TaskManager", StubTaskManager),
        # Mock _loop_validate_step to return complete
        patch.object(
            orchestrator,
            "_loop_validate_step",
            new_callable=AsyncMock,
            return_value=(True, []),
        ) as mock_validate,
    ):
        mock_plan.return_value = (decomp, "thinking")
        mock_pm.read_project_md = AsyncMock(return_value=md)
        mock_pm.write_project_md = AsyncMock()

        events = await _collect(orchestrator._execute_step(project_id, 1))

    statuses = [
        e["data"]["status"]
        for e in events
        if e["event"] == "build_step_update"
    ]

    # 'reviewing' event must appear
    assert "reviewing" in statuses, (
        f"Expected 'reviewing' with BUILD_LOOP_REVIEW=True, got: {statuses}"
    )

    # _loop_validate_step called exactly once
    mock_validate.assert_called_once()

    # No retry — still only one TaskManager pass
    assert StubTaskManager.call_count == 1, (
        f"Expected 1 TaskManager pass (complete, no retry), got {StubTaskManager.call_count}"
    )

    # review_agent.review must NOT be called (flag-on path)
    mock_review.review.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: BUILD_LOOP_REVIEW=True + returns missing → one retry, capped
# ---------------------------------------------------------------------------

async def test_loop_review_true_missing_triggers_retry(orchestrator, project_md):
    """BUILD_LOOP_REVIEW=True + missing: one retry pass, capped at BUILD_MAX_REVIEW_RETRIES."""
    project_id = "proj-cr-003"
    md = project_md
    _prime_state(orchestrator, project_id, md)
    decomp = _make_decomp(1)

    # First call: incomplete (missing); second call: complete
    validate_returns = [(False, "缺少计分板初始化命令"), (True, [])]
    validate_iter = iter(validate_returns)

    async def mock_validate_side_effect(*args, **kwargs):
        return next(validate_iter)

    with (
        patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", True),
        patch("backend.build.build_orchestrator.BUILD_LOOP_REVIEW", True),
        patch("backend.build.build_orchestrator.BUILD_MAX_REVIEW_RETRIES", 2),
        patch.object(orchestrator.planner, "plan", new_callable=AsyncMock) as mock_plan,
        patch("backend.build.build_orchestrator.project_manager") as mock_pm,
        patch("backend.build.build_orchestrator.review_agent") as mock_review,
        patch("backend.build.build_orchestrator.write_agent"),
        patch("backend.build.build_orchestrator.TaskManager", StubTaskManager),
        patch.object(
            orchestrator,
            "_loop_validate_step",
            side_effect=mock_validate_side_effect,
        ) as mock_validate,
    ):
        mock_plan.return_value = (decomp, "thinking")
        mock_pm.read_project_md = AsyncMock(return_value=md)
        mock_pm.write_project_md = AsyncMock()

        events = await _collect(orchestrator._execute_step(project_id, 1))

    statuses = [
        e["data"]["status"]
        for e in events
        if e["event"] == "build_step_update"
    ]

    # 'reviewing' must appear (at least once)
    reviewing_count = statuses.count("reviewing")
    assert reviewing_count >= 1, (
        f"Expected at least one 'reviewing' event, got: {statuses}"
    )

    # Validate called twice: once before retry, once after
    assert mock_validate.call_count == 2, (
        f"Expected 2 validate calls (fail then pass), got {mock_validate.call_count}"
    )

    # Two TaskManager passes: initial + one retry
    assert StubTaskManager.call_count == 2, (
        f"Expected 2 TaskManager passes (initial + retry), got {StubTaskManager.call_count}"
    )

    # Missing text must have been appended to the retry plan call
    # (second plan call should include 缺少计分板初始化命令)
    plan_call_args = [str(c) for c in mock_plan.call_args_list]
    assert any("缺少计分板初始化命令" in arg for arg in plan_call_args), (
        f"Expected missing text in retry plan call, plan calls: {plan_call_args}"
    )

    # review_agent.review must NOT be called
    mock_review.review.assert_not_called()


# ---------------------------------------------------------------------------
# Test 4: BUILD_LOOP_REVIEW=True capped at BUILD_MAX_REVIEW_RETRIES
# ---------------------------------------------------------------------------

async def test_loop_review_true_capped_at_max_retries(orchestrator, project_md):
    """BUILD_LOOP_REVIEW=True + always missing: capped at BUILD_MAX_REVIEW_RETRIES retries."""
    project_id = "proj-cr-004"
    md = project_md
    _prime_state(orchestrator, project_id, md)
    decomp = _make_decomp(1)
    max_retries = 2  # BUILD_MAX_REVIEW_RETRIES default

    with (
        patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", True),
        patch("backend.build.build_orchestrator.BUILD_LOOP_REVIEW", True),
        patch("backend.build.build_orchestrator.BUILD_MAX_REVIEW_RETRIES", max_retries),
        patch.object(orchestrator.planner, "plan", new_callable=AsyncMock) as mock_plan,
        patch("backend.build.build_orchestrator.project_manager") as mock_pm,
        patch("backend.build.build_orchestrator.review_agent") as mock_review,
        patch("backend.build.build_orchestrator.write_agent"),
        patch("backend.build.build_orchestrator.TaskManager", StubTaskManager),
        # Always returns incomplete
        patch.object(
            orchestrator,
            "_loop_validate_step",
            new_callable=AsyncMock,
            return_value=(False, "持续缺失"),
        ) as mock_validate,
    ):
        mock_plan.return_value = (decomp, "thinking")
        mock_pm.read_project_md = AsyncMock(return_value=md)
        mock_pm.write_project_md = AsyncMock()

        events = await _collect(orchestrator._execute_step(project_id, 1))

    # validate called at most max_retries+1 times (initial + up to max_retries)
    assert mock_validate.call_count <= max_retries + 1, (
        f"Expected at most {max_retries + 1} validate calls, got {mock_validate.call_count}"
    )

    # TaskManager called at most max_retries+1 times (initial + retries)
    assert StubTaskManager.call_count <= max_retries + 1, (
        f"Expected at most {max_retries + 1} TaskManager passes, "
        f"got {StubTaskManager.call_count}"
    )

    # Execution still completes (no crash/exception)
    statuses = [
        e["data"]["status"]
        for e in events
        if e["event"] == "build_step_update"
    ]
    assert "complete" in statuses, (
        f"Expected 'complete' even after max retries, got: {statuses}"
    )

    # review_agent.review must NOT be called
    mock_review.review.assert_not_called()


# ---------------------------------------------------------------------------
# Test 5: review_agent.review never called regardless of BUILD_LOOP_REVIEW (flag-on)
# ---------------------------------------------------------------------------

async def test_old_review_agent_never_called_with_flag_on(orchestrator, project_md):
    """review_agent.review is never called when BUILD_USE_AGENT_LOOP=True."""
    project_id = "proj-cr-005"
    md = project_md
    _prime_state(orchestrator, project_id, md)
    decomp = _make_decomp(1)

    for loop_review in (False, True):
        StubTaskManager.reset()
        with (
            patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", True),
            patch("backend.build.build_orchestrator.BUILD_LOOP_REVIEW", loop_review),
            patch.object(orchestrator.planner, "plan", new_callable=AsyncMock,
                         return_value=(decomp, "")),
            patch("backend.build.build_orchestrator.project_manager") as mock_pm,
            patch("backend.build.build_orchestrator.review_agent") as mock_review,
            patch("backend.build.build_orchestrator.write_agent"),
            patch("backend.build.build_orchestrator.TaskManager", StubTaskManager),
            patch.object(orchestrator, "_loop_validate_step",
                         new_callable=AsyncMock, return_value=(True, [])),
        ):
            mock_pm.read_project_md = AsyncMock(return_value=md)
            mock_pm.write_project_md = AsyncMock()

            await _collect(orchestrator._execute_step(project_id, 1))

            mock_review.review.assert_not_called(), (
                f"review_agent.review should never be called with BUILD_USE_AGENT_LOOP=True "
                f"(BUILD_LOOP_REVIEW={loop_review})"
            )
