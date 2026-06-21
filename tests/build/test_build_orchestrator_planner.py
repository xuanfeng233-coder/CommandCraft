"""Tests for BuildOrchestrator BUILD_USE_AGENT_LOOP flag-on path.

Covers:
1. flag-on: event sequence build_phase(planning)→thinking→build_plan→build_phase(reviewing)→done,
   no build_clarify emitted.
2. flag-on: clarify/search/write agents NOT called.
3. flag-on: state.total_steps == len(decomp.tasks); build_plan.markdown_content round-trips.
4. flag-off: clarify_agent.analyze IS called (regression guard).
5. flag-on: Planner raises PlannerParseError → error+done emitted.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.agents.planner import PlannerParseError
from backend.agents.planner_schemas import Decomposition, TaskDef
from backend.build.agents.reader_agent import reader_agent
from backend.build.build_orchestrator import BuildOrchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_decomp(n: int = 3) -> Decomposition:
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


async def _collect(gen) -> list[dict]:
    """Drain an async generator into a list of event dicts."""
    events = []
    async for ev in gen:
        events.append(ev)
    return events


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def orchestrator():
    """Return a BuildOrchestrator with project_manager mocked out."""
    orch = BuildOrchestrator()
    return orch


# ---------------------------------------------------------------------------
# 1 & 2 & 3: flag-on happy path
# ---------------------------------------------------------------------------

async def test_flag_on_event_sequence_no_clarify(orchestrator):
    """flag-on: emits planning→thinking→build_plan→reviewing→done; no build_clarify."""
    decomp = _make_decomp(3)

    with (
        patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", True),
        patch.object(orchestrator.planner, "plan", new_callable=AsyncMock) as mock_plan,
        patch("backend.build.build_orchestrator.project_manager") as mock_pm,
        patch("backend.build.build_orchestrator.clarify_agent") as mock_clarify,
        patch("backend.build.build_orchestrator.search_agent") as mock_search,
        patch("backend.build.build_orchestrator.write_agent") as mock_write,
    ):
        mock_plan.return_value = (decomp, "thinking text")
        mock_pm.create_project = AsyncMock(return_value="proj-001")
        mock_pm.update_status = AsyncMock()

        events = await _collect(
            orchestrator.start_build("做个计分板系统", device_fp="fp-test")
        )

    event_names = [e["event"] for e in events]

    # Must contain planning phase first
    assert event_names[0] == "build_phase"
    assert events[0]["data"]["phase"] == "planning"

    # Must contain thinking (from _plan_via_planner)
    assert "thinking" in event_names

    # Must contain build_plan
    assert "build_plan" in event_names

    # Must contain reviewing phase
    reviewing_events = [e for e in events if e["event"] == "build_phase" and e["data"].get("phase") == "reviewing"]
    assert len(reviewing_events) == 1

    # Must end with done
    assert event_names[-1] == "done"

    # Must NOT contain build_clarify
    assert "build_clarify" not in event_names


async def test_flag_on_clarify_search_write_not_called(orchestrator):
    """flag-on: clarify_agent.analyze / search_agent.search / write_agent.create_plan NOT called."""
    decomp = _make_decomp(2)

    with (
        patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", True),
        patch.object(orchestrator.planner, "plan", new_callable=AsyncMock) as mock_plan,
        patch("backend.build.build_orchestrator.project_manager") as mock_pm,
        patch("backend.build.build_orchestrator.clarify_agent") as mock_clarify,
        patch("backend.build.build_orchestrator.search_agent") as mock_search,
        patch("backend.build.build_orchestrator.write_agent") as mock_write,
    ):
        mock_plan.return_value = (decomp, "")
        mock_pm.create_project = AsyncMock(return_value="proj-002")
        mock_pm.update_status = AsyncMock()
        mock_clarify.analyze = AsyncMock()
        mock_search.search = AsyncMock()
        mock_write.create_plan = AsyncMock()

        await _collect(orchestrator.start_build("测试请求", device_fp="fp-test"))

    mock_clarify.analyze.assert_not_called()
    mock_search.search.assert_not_called()
    mock_write.create_plan.assert_not_called()


async def test_flag_on_total_steps_and_roundtrip(orchestrator):
    """flag-on: state.total_steps == len(decomp.tasks); build_plan markdown round-trips."""
    decomp = _make_decomp(4)

    with (
        patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", True),
        patch.object(orchestrator.planner, "plan", new_callable=AsyncMock) as mock_plan,
        patch("backend.build.build_orchestrator.project_manager") as mock_pm,
    ):
        mock_plan.return_value = (decomp, "")
        mock_pm.create_project = AsyncMock(return_value="proj-003")
        mock_pm.update_status = AsyncMock()

        events = await _collect(
            orchestrator.start_build("四步任务", device_fp="fp-test")
        )

    # Get the build state
    project_id = events[0]["data"]["project_id"]
    state = orchestrator.get_build_state(project_id)
    assert state is not None
    assert state.total_steps == len(decomp.tasks)  # == 4

    # Find build_plan event and verify markdown round-trips
    build_plan_events = [e for e in events if e["event"] == "build_plan"]
    assert len(build_plan_events) == 1
    md = build_plan_events[0]["data"]["markdown_content"]
    steps = reader_agent.parse_plan(md)
    assert len(steps) == len(decomp.tasks)  # 4 steps parse back to 4


# ---------------------------------------------------------------------------
# 4: flag-off regression guard
# ---------------------------------------------------------------------------

async def test_flag_off_calls_clarify_agent(orchestrator):
    """flag-off: clarify_agent.analyze IS called (existing branch untouched)."""
    from backend.build.agents.clarify_agent import ClarifyResult

    clarify_result = ClarifyResult(
        needs_clarification=False,
        requirements_summary="需求已明确",
        questions=[],
        suggested_steps=["步骤1"],
        needs_search=False,
        search_queries=[],
    )

    with (
        patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", False),
        patch("backend.build.build_orchestrator.project_manager") as mock_pm,
        patch("backend.build.build_orchestrator.clarify_agent") as mock_clarify,
        patch("backend.build.build_orchestrator.write_agent") as mock_write,
    ):
        mock_pm.create_project = AsyncMock(return_value="proj-004")
        mock_pm.update_status = AsyncMock()
        mock_clarify.analyze = AsyncMock(return_value=clarify_result)
        mock_write.create_plan = AsyncMock(return_value="## 步骤 1: 测试 [ ]\n**需求**: 测试\n**实现思路**: 做\n**涉及命令**: /say\n- [ ] 做\n")

        await _collect(orchestrator.start_build("测试flag-off", device_fp="fp-test"))

    mock_clarify.analyze.assert_called_once()


# ---------------------------------------------------------------------------
# 5: Planner raises PlannerParseError → error + done
# ---------------------------------------------------------------------------

async def test_flag_on_planner_error_emits_error_and_done(orchestrator):
    """flag-on: PlannerParseError → error event + done event emitted."""
    with (
        patch("backend.build.build_orchestrator.BUILD_USE_AGENT_LOOP", True),
        patch.object(orchestrator.planner, "plan", new_callable=AsyncMock) as mock_plan,
        patch("backend.build.build_orchestrator.project_manager") as mock_pm,
    ):
        mock_plan.side_effect = PlannerParseError("修复耗尽，无法解析")
        mock_pm.create_project = AsyncMock(return_value="proj-005")
        mock_pm.update_status = AsyncMock()

        events = await _collect(
            orchestrator.start_build("会失败的请求", device_fp="fp-test")
        )

    event_names = [e["event"] for e in events]
    assert "error" in event_names
    assert event_names[-1] == "done"
    # Should not have a successful build_plan
    assert "build_plan" not in event_names
