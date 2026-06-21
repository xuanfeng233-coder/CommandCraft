"""BuildOrchestrator — Three-phase build workflow engine.

Phase A: Planning  — ClarifyAgent → (optional clarify) → search → WriteAgent
Phase B: Review    — user edits plan → confirm → save PROJECT.md
Phase C: Execution — read step → decompose (with context chain) → execute → review → update
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from backend.agents.main_agent import MainAgent
from backend.agents.planner import Planner, PlannerParseError
from backend.agents.planner_schemas import Decomposition, to_legacy_decomposition
from backend.agentloop.loop import AgentLoop
from backend.agentloop.schemas import FinishReason, LoopBudget
from backend.agentloop.step import build_step
from backend.agentloop.tools.finish import build_default_registry
from backend.build.agents.clarify_agent import ClarifyResult, clarify_agent
from backend.build.agents.reader_agent import reader_agent
from backend.build.agents.review_agent import review_agent
from backend.build.agents.search_agent import search_agent
from backend.build.agents.write_agent import write_agent
from backend.build.plan_adapter import decomposition_to_project_md
from backend.build.project_manager import project_manager
from backend.config import (
    BUILD_LOOP_REVIEW,
    BUILD_MAX_REVIEW_RETRIES,
    BUILD_SESSION_TTL,
    BUILD_USE_AGENT_LOOP,
)
from backend.orchestrator.orchestrator import TaskManager
from backend.subscription.llm_context import get_build_chat_client

logger = logging.getLogger(__name__)


@dataclass
class BuildState:
    project_id: str
    device_fp: str
    user_input: str = ""
    edition: str = "bedrock"
    status: str = "planning"  # planning | clarifying | reviewing | executing | completed
    current_step: int = 0
    total_steps: int = 0
    plan_content: str = ""
    accumulated_context: str = ""
    clarify_context: ClarifyResult | None = None
    clarify_answers: dict[str, str] = field(default_factory=dict)
    all_commands: list[str] = field(default_factory=list)
    task_manager: TaskManager | None = None
    planner_decomposition: Decomposition | None = None
    created_at: float = field(default_factory=time.time)

    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > BUILD_SESSION_TTL


class BuildOrchestrator:
    """Core build workflow engine."""

    def __init__(self) -> None:
        self.main_agent = MainAgent()
        self.planner = Planner()
        self._active_builds: dict[str, BuildState] = {}

    # ------------------------------------------------------------------
    # Phase A: Planning (with ClarifyAgent gamification)
    # ------------------------------------------------------------------

    async def start_build(
        self,
        user_input: str,
        device_fp: str,
        session_id: str = "",
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Phase A: ClarifyAgent analyses → optional clarify → generate plan.

        Yields SSE events throughout the process.
        """
        self._cleanup_expired()

        # Create project
        project_id = await project_manager.create_project(
            device_fp=device_fp,
            title=user_input[:50],
        )

        state = BuildState(
            project_id=project_id,
            device_fp=device_fp,
            user_input=user_input,
            status="planning",
        )
        self._active_builds[project_id] = state

        yield _sse("build_phase", {"phase": "planning", "project_id": project_id})

        # Flag-on: use Planner agent loop path (BUILD_USE_AGENT_LOOP=true)
        if BUILD_USE_AGENT_LOOP:
            async for ev in self._plan_via_planner(project_id, user_input, state):
                yield ev
            return

        # Step 1: ClarifyAgent gamification analysis
        yield _sse("thinking", {"text": "正在分析构建需求...\n"})

        clarify_result = await clarify_agent.analyze(user_input)
        state.clarify_context = clarify_result

        # Step 2: Gamification conclusion — need clarification?
        if clarify_result.needs_clarification:
            state.status = "clarifying"
            # Ensure each question has a unique key for the frontend
            questions_with_keys = []
            for i, q in enumerate(clarify_result.questions):
                qc = dict(q) if isinstance(q, dict) else {"question": str(q)}
                if "key" not in qc:
                    qc["key"] = f"q-{i}"
                questions_with_keys.append(qc)

            yield _sse("build_clarify", {
                "project_id": project_id,
                "summary": clarify_result.requirements_summary,
                "questions": questions_with_keys,
                "suggested_steps": clarify_result.suggested_steps,
            })
            yield _sse("done", {"project_id": project_id})
            return  # Wait for POST /api/build/{id}/clarify

        # No clarification needed — emit summary and proceed directly
        if clarify_result.requirements_summary:
            yield _sse("thinking", {"text": clarify_result.requirements_summary + "\n"})

        async for event in self._generate_plan(project_id, user_input, state):
            yield event

    # ------------------------------------------------------------------
    # Flag-on: Planner agent loop path
    # ------------------------------------------------------------------

    async def _plan_via_planner(
        self,
        project_id: str,
        user_input: str,
        state: BuildState,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Generate PROJECT.md via Planner (BUILD_USE_AGENT_LOOP=true path).

        Emits: thinking → build_plan{markdown_content} → build_phase(reviewing) → done.
        Does NOT emit build_clarify.
        """
        yield _sse("thinking", {"text": "正在规划构建方案...\n"})

        try:
            decomp, _thinking = await self.planner.plan(
                user_input,
                session_context="",
                client=get_build_chat_client(),
                edition=state.edition,
            )
        except (PlannerParseError, Exception) as e:
            logger.error("Planner failed for project %s: %s", project_id, e)
            yield _sse("error", {"message": f"规划失败: {e}"})
            yield _sse("done", {"project_id": project_id})
            return

        state.planner_decomposition = decomp
        md = decomposition_to_project_md(decomp, user_input)
        state.plan_content = md

        steps = reader_agent.parse_plan(md)
        state.total_steps = len(steps)
        await project_manager.update_status(
            project_id,
            title=user_input[:50],
            total_steps=len(steps),
        )

        yield _sse("build_plan", {"markdown_content": md})
        yield _sse("build_phase", {"phase": "reviewing", "project_id": project_id})
        yield _sse("done", {"project_id": project_id})

    # ------------------------------------------------------------------
    # Continue after clarification
    # ------------------------------------------------------------------

    async def continue_after_clarify(
        self,
        project_id: str,
        answers: dict[str, str],
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Resume planning after user answers clarification questions."""
        state = self._active_builds.get(project_id)
        if not state:
            yield _sse("error", {"message": "构建会话不存在或已过期"})
            return

        state.clarify_answers = answers
        state.status = "planning"

        yield _sse("build_phase", {"phase": "planning", "project_id": project_id})
        yield _sse("thinking", {"text": "收到补充信息，正在生成构建方案...\n"})

        async for event in self._generate_plan(
            project_id, state.user_input, state
        ):
            yield event

    # ------------------------------------------------------------------
    # Plan generation (shared by start_build and continue_after_clarify)
    # ------------------------------------------------------------------

    async def _generate_plan(
        self,
        project_id: str,
        user_input: str,
        state: BuildState,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Generate PROJECT.md from user request + clarify context + search results."""
        # Optional search
        search_results = None
        if state.clarify_context and state.clarify_context.needs_search:
            search_results = []
            for query in state.clarify_context.search_queries:
                yield _sse("search_activity", {"query": query, "status": "searching"})
                results = await search_agent.search(query, user_input)
                search_results.extend(results)
                yield _sse("search_activity", {
                    "query": query,
                    "status": "done",
                    "results_count": len(results),
                })

        # WriteAgent generates plan
        yield _sse("thinking", {"text": "正在生成构建方案...\n"})

        plan_content = await write_agent.create_plan(
            user_request=user_input,
            clarify_context=state.clarify_context,
            clarify_answers=state.clarify_answers or None,
            search_results=search_results,
        )

        state.plan_content = plan_content

        # Update project metadata
        steps = reader_agent.parse_plan(plan_content)
        state.total_steps = len(steps)
        await project_manager.update_status(
            project_id,
            title=user_input[:50],
            total_steps=len(steps),
        )

        yield _sse("build_plan", {"markdown_content": plan_content})
        yield _sse("build_phase", {"phase": "reviewing", "project_id": project_id})
        yield _sse("done", {"project_id": project_id})

    # ------------------------------------------------------------------
    # Phase B→C: Confirm plan and begin execution
    # ------------------------------------------------------------------

    async def confirm_plan(
        self,
        project_id: str,
        plan_content: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Phase B→C: Save final plan and execute all steps.

        Args:
            project_id: The build project ID.
            plan_content: User-edited plan (None = use original).
        """
        state = self._active_builds.get(project_id)
        if not state:
            yield _sse("error", {"message": "构建会话不存在或已过期"})
            return

        # Use user-edited plan if provided
        if plan_content is not None:
            state.plan_content = plan_content

        # Save to PROJECT.md
        await project_manager.write_project_md(project_id, state.plan_content)

        # Parse steps
        steps = reader_agent.parse_plan(state.plan_content)
        state.total_steps = len(steps)
        state.status = "executing"
        state.accumulated_context = ""

        await project_manager.update_status(
            project_id,
            status="executing",
            total_steps=len(steps),
        )

        yield _sse("build_phase", {"phase": "executing", "project_id": project_id})

        # Execute all steps
        async for event in self._execute_all_steps(project_id):
            yield event

    # ------------------------------------------------------------------
    # Phase C: Step execution loop (with context chain)
    # ------------------------------------------------------------------

    async def _execute_all_steps(
        self,
        project_id: str,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Execute all steps sequentially."""
        state = self._active_builds.get(project_id)
        if not state:
            return

        for step_idx in range(1, state.total_steps + 1):
            state.current_step = step_idx
            await project_manager.update_status(project_id, step_index=step_idx)

            async for event in self._execute_step(project_id, step_idx):
                yield event

        # All done
        state.status = "completed"
        await project_manager.update_status(project_id, status="completed")

        # Build final integrated layout
        final_md = await project_manager.read_project_md(project_id)
        yield _sse("build_phase", {
            "phase": "completed",
            "project_id": project_id,
            "plan_content": final_md,
            "commands": state.all_commands,
        })
        yield _sse("done", {"project_id": project_id})

    async def _execute_step(
        self,
        project_id: str,
        step_index: int,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Execute a single step with review retry loop and context chain."""
        # flag-on: route to agent-loop path (no ReviewAgent, no retry)
        if BUILD_USE_AGENT_LOOP:
            async for ev in self._execute_step_loop(project_id, step_index):
                yield ev
            return

        state = self._active_builds.get(project_id)
        if not state:
            return

        yield _sse("build_step_update", {"step_index": step_index, "status": "reading"})

        # Read current step from PROJECT.md
        md_content = await project_manager.read_project_md(project_id)
        step = reader_agent.get_step(md_content, step_index)

        if not step:
            yield _sse("build_step_update", {
                "step_index": step_index,
                "status": "failed",
                "error": f"步骤 {step_index} 未找到",
            })
            return

        # Build the step request for MainAgent
        step_request = self._build_step_request(step)

        # Build accumulated execution context (context chain)
        execution_context = self._build_execution_context(state, step_index)

        retry_count = 0
        all_completed_results: list[dict[str, Any]] = []

        while retry_count <= BUILD_MAX_REVIEW_RETRIES:
            yield _sse("build_step_update", {
                "step_index": step_index,
                "status": "decomposing" if retry_count == 0 else "retrying",
                "retry": retry_count,
            })

            # Decompose step into tasks — use chat model + context
            decomposition = await self.main_agent.decompose(
                step_request,
                execution_context,
                client=get_build_chat_client(),
            )
            decomposition.pop("_thinking", "")

            tasks = decomposition.get("tasks", [])
            if not tasks:
                yield _sse("build_step_update", {
                    "step_index": step_index,
                    "status": "failed",
                    "error": "任务分解失败",
                })
                return

            # Emit task list for this step
            yield _sse("task_list", {
                "project_name": f"步骤 {step_index}: {step.title}",
                "overview": step.requirement,
                "tasks": [
                    {
                        "task_id": t.get("task_id", str(i + 1)),
                        "description": t.get("description", ""),
                        "depends_on": t.get("depends_on", []),
                        "status": "blocked" if t.get("depends_on") else "pending",
                    }
                    for i, t in enumerate(tasks)
                ],
            })

            # Execute tasks
            yield _sse("build_step_update", {
                "step_index": step_index,
                "status": "executing",
            })

            mgr = TaskManager(decomposition)
            async for event in mgr.execute_all():
                yield event

            completed_results = mgr.get_completed_results()
            all_completed_results.extend(completed_results)

            # Review
            yield _sse("build_step_update", {
                "step_index": step_index,
                "status": "reviewing",
            })

            review_result = await review_agent.review(
                step_plan=step.raw_content,
                task_results=completed_results,
            )

            if review_result.complete:
                break

            # Not complete — retry with missing items
            retry_count += 1
            if retry_count <= BUILD_MAX_REVIEW_RETRIES:
                missing_text = "\n".join(f"- {m}" for m in review_result.missing_items)
                step_request = (
                    f"{step_request}\n\n"
                    f"## 审查反馈（缺失项）\n{missing_text}\n"
                    f"请补充以上缺失的命令。"
                )
                yield _sse("thinking", {
                    "text": f"步骤 {step_index} 审查发现缺失项，正在补充...\n",
                })

        # Collect commands from this step for final editor insertion
        state.all_commands.extend(self._extract_all_commands(all_completed_results))

        # Extract step artifacts and update accumulated context
        state.accumulated_context = self._extract_step_artifacts(
            state.accumulated_context, step_index, step, all_completed_results,
        )

        # Update PROJECT.md
        yield _sse("build_step_update", {
            "step_index": step_index,
            "status": "updating",
        })

        # Build result summary
        result_summary = self._build_result_summary(all_completed_results)
        command_layout = self._build_command_layout_text(all_completed_results)

        updated_md = await write_agent.mark_step_done(
            md_content=await project_manager.read_project_md(project_id),
            step_index=step_index,
            summary=result_summary,
            command_layout=command_layout,
        )
        await project_manager.write_project_md(project_id, updated_md)

        yield _sse("build_step_update", {
            "step_index": step_index,
            "status": "complete",
            "result_summary": result_summary,
        })

    # ------------------------------------------------------------------
    # Flag-on: agent-loop execution path (no ReviewAgent retry)
    # ------------------------------------------------------------------

    async def _execute_step_loop(
        self,
        project_id: str,
        step_index: int,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Execute a single build step via Planner + TaskManager(use_loop=True).

        No ReviewAgent, no retry loop — one TaskManager pass per step.
        PROJECT.md is marked done via deterministic regex (_regex_mark_step_done).
        """
        state = self._active_builds.get(project_id)
        if not state:
            return

        # 1. Read step
        yield _sse("build_step_update", {"step_index": step_index, "status": "reading"})

        md_content = await project_manager.read_project_md(project_id)
        step = reader_agent.get_step(md_content, step_index)

        if not step:
            yield _sse("build_step_update", {
                "step_index": step_index,
                "status": "failed",
                "error": f"步骤 {step_index} 未找到",
            })
            return

        # 2. Build step request + execution context (reuse existing helpers)
        step_request = self._build_step_request(step)
        execution_context = self._build_execution_context(state, step_index)

        # 3. Decompose via Planner
        yield _sse("build_step_update", {"step_index": step_index, "status": "decomposing"})

        try:
            decomp, _ = await self.planner.plan(
                step_request,
                session_context=execution_context,
                client=get_build_chat_client(),
                edition=state.edition,
            )
        except (PlannerParseError, Exception) as e:
            logger.error(
                "Planner failed for project %s step %d: %s", project_id, step_index, e
            )
            yield _sse("build_step_update", {
                "step_index": step_index,
                "status": "failed",
                "error": f"分解失败: {e}",
            })
            return

        legacy = to_legacy_decomposition(decomp, original_input=step_request)
        tasks = legacy.get("tasks", [])

        if not tasks:
            yield _sse("build_step_update", {
                "step_index": step_index,
                "status": "failed",
                "error": "任务分解结果为空",
            })
            return

        # 4. Emit task list (mirror the flag-off shape)
        yield _sse("task_list", {
            "project_name": f"步骤 {step_index}: {step.title}",
            "overview": step.requirement,
            "tasks": [
                {
                    "task_id": t.get("task_id", str(i + 1)),
                    "description": t.get("description", ""),
                    "depends_on": t.get("depends_on", []),
                    "status": "blocked" if t.get("depends_on") else "pending",
                }
                for i, t in enumerate(tasks)
            ],
        })

        # 5. Execute via TaskManager(use_loop=True) — routes to _run_via_agentloop
        yield _sse("build_step_update", {"step_index": step_index, "status": "executing"})

        mgr = TaskManager(legacy, edition=state.edition)
        mgr.use_loop = True
        async for ev in mgr.execute_all():
            yield ev

        # 6. Collect results and update accumulated context
        completed_results = mgr.get_completed_results()
        all_completed_results: list[dict[str, Any]] = list(completed_results)

        # 6a. Optional completeness review (BUILD_LOOP_REVIEW sub-flag, default off)
        if BUILD_LOOP_REVIEW:
            retry_count = 0
            while retry_count <= BUILD_MAX_REVIEW_RETRIES:
                yield _sse("build_step_update", {
                    "step_index": step_index,
                    "status": "reviewing",
                })

                ok, missing = await self._loop_validate_step(
                    step, all_completed_results, state.edition
                )

                if ok:
                    break

                retry_count += 1
                if retry_count > BUILD_MAX_REVIEW_RETRIES:
                    break

                # Re-plan with missing items appended to step_request
                missing_text = (
                    missing if isinstance(missing, str)
                    else "\n".join(f"- {m}" for m in missing)
                )
                step_request = (
                    f"{step_request}\n\n"
                    f"## 完整性审查（缺失项）\n{missing_text}\n"
                    f"请补充以上缺失的命令。"
                )
                yield _sse("thinking", {
                    "text": f"步骤 {step_index} 完整性检查发现缺失项，正在补充...\n",
                })

                # Re-decompose and re-execute one pass
                try:
                    decomp2, _ = await self.planner.plan(
                        step_request,
                        session_context=execution_context,
                        client=get_build_chat_client(),
                        edition=state.edition,
                    )
                except (PlannerParseError, Exception) as e:
                    logger.warning(
                        "Planner failed during loop-review retry for project %s step %d: %s",
                        project_id, step_index, e,
                    )
                    break

                legacy2 = to_legacy_decomposition(decomp2, original_input=step_request)
                if not legacy2.get("tasks"):
                    break

                yield _sse("build_step_update", {
                    "step_index": step_index,
                    "status": "executing",
                })
                mgr2 = TaskManager(legacy2, edition=state.edition)
                mgr2.use_loop = True
                async for ev in mgr2.execute_all():
                    yield ev

                all_completed_results.extend(mgr2.get_completed_results())

        state.all_commands.extend(self._extract_all_commands(all_completed_results))
        state.accumulated_context = self._extract_step_artifacts(
            state.accumulated_context, step_index, step, all_completed_results,
        )

        # 7. Mark step done in PROJECT.md via deterministic regex (no LLM)
        yield _sse("build_step_update", {"step_index": step_index, "status": "updating"})

        result_summary = self._build_result_summary(all_completed_results)
        command_layout = self._build_command_layout_text(all_completed_results)

        fresh_md = await project_manager.read_project_md(project_id)
        updated_md = _regex_mark_step_done(fresh_md, step_index, result_summary, command_layout)
        await project_manager.write_project_md(project_id, updated_md)

        yield _sse("build_step_update", {
            "step_index": step_index,
            "status": "complete",
            "result_summary": result_summary,
        })

    # ------------------------------------------------------------------
    # Completeness validation (BUILD_LOOP_REVIEW path)
    # ------------------------------------------------------------------

    async def _loop_validate_step(
        self,
        step: Any,
        results: list[dict[str, Any]],
        edition: str,
    ) -> tuple[bool, list[str] | str]:
        """Run a focused completeness check via AgentLoop.

        Returns (ok, missing) where:
        - ok=True  → step is complete (finish reason == done)
        - ok=False → step is incomplete; missing contains description text
        """
        # Build a compact summary of collected commands from results
        commands = self._extract_all_commands(results)
        cmd_text = "\n".join(f"- {c}" for c in commands) if commands else "（无）"

        messages = [
            {
                "role": "system",
                "content": (
                    "你是一个 Minecraft 命令完整性检查器。"
                    "根据步骤需求和已生成的命令，判断是否完整覆盖了需求。"
                    "完整→ finish(reason=done)；有遗漏→ finish(reason=give_up, "
                    "final_answer=缺失的具体项目描述)。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"## 步骤需求\n{step.requirement or step.title}\n\n"
                    f"## 已生成命令\n{cmd_text}\n\n"
                    "请判断以上命令是否完整覆盖了步骤需求。"
                ),
            },
        ]

        loop = AgentLoop(
            registry=build_default_registry(),
            step=build_step(client=get_build_chat_client()),
            budget=LoopBudget(max_rounds=3, warn_at_round=2),
            edition=edition,
        )

        outcome = None
        async for ev in loop.run(messages):
            if ev.get("event") == "_agent_outcome":
                outcome = ev["data"]["outcome"]

        if outcome is None:
            # Shouldn't happen; treat as complete to avoid infinite retries
            return True, []

        if outcome.reason == FinishReason.DONE:
            return True, []

        # give_up / ask_user / implicit → treat as incomplete
        missing_text = outcome.content or "步骤命令不完整"
        return False, missing_text

    # ------------------------------------------------------------------
    # Context chain helpers
    # ------------------------------------------------------------------

    def _build_execution_context(self, state: BuildState, current_step_index: int) -> str:
        """Build context passed to MainAgent.decompose for a step.

        Includes:
        1. Project overview (from PROJECT.md)
        2. User clarification answers
        3. Predecessor step artifacts (accumulated_context)
        """
        parts: list[str] = []

        # Project overview
        if state.plan_content:
            overview = reader_agent.get_overview(state.plan_content)
            if overview:
                parts.append(f"## 项目概述\n{overview}")

        # User clarification answers
        if state.clarify_answers:
            answers_text = "\n".join(
                f"- {k}: {v}" for k, v in state.clarify_answers.items()
            )
            parts.append(f"## 用户需求补充\n{answers_text}")

        # Predecessor step artifacts
        if state.accumulated_context:
            parts.append(f"## 前序步骤产出\n{state.accumulated_context}")

        return "\n\n".join(parts)

    @staticmethod
    def _extract_step_artifacts(
        existing_context: str,
        step_index: int,
        step: Any,
        results: list[dict[str, Any]],
    ) -> str:
        """Extract key artifacts from step results and append to accumulated context.

        Extracts:
        - Scoreboard names (scoreboard objectives add <name>)
        - Tag names (tag @s add <name>)
        - Generated commands
        """
        artifacts = [f"### 步骤 {step_index}: {step.title}"]
        commands: list[str] = []

        for tr in results:
            result = tr.get("result", {})
            if result.get("type") == "single_command":
                cmd = result.get("command", {}).get("command", "")
                if cmd:
                    commands.extend(cmd.split("\n"))
            elif result.get("type") == "project":
                for phase in result.get("phases", []):
                    for task in phase.get("tasks", []):
                        for block in task.get("command_blocks", []):
                            if block.get("command"):
                                commands.append(block["command"])

        if commands:
            artifacts.append("命令: " + "; ".join(commands[:10]))

        # Regex extract key identifiers
        scoreboards: set[str] = set()
        tags: set[str] = set()
        for cmd in commands:
            scoreboards.update(re.findall(r"scoreboard objectives add (\w+)", cmd))
            tags.update(re.findall(r"tag\s+\S+\s+add\s+(\w+)", cmd))

        if scoreboards:
            artifacts.append(f"计分板: {', '.join(scoreboards)}")
        if tags:
            artifacts.append(f"标签: {', '.join(tags)}")

        new_entry = "\n".join(artifacts)
        return f"{existing_context}\n{new_entry}" if existing_context else new_entry

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_all_commands(results: list[dict[str, Any]]) -> list[str]:
        """Extract all command strings from task results."""
        commands: list[str] = []
        for tr in results:
            result = tr.get("result", {})
            result_type = result.get("type", "")

            if result_type in ("single_command", "execute_chain", "selector", "rawtext"):
                cmd_obj = result.get("command", {})
                if isinstance(cmd_obj, dict) and cmd_obj.get("command"):
                    for line in cmd_obj["command"].split("\n"):
                        line = line.strip()
                        if line:
                            commands.append(line)
            elif result_type == "project":
                for phase in result.get("phases", []):
                    for task in phase.get("tasks", []):
                        for block in task.get("command_blocks", []):
                            if block.get("command"):
                                commands.append(block["command"])
        return commands

    @staticmethod
    def _build_step_request(step: Any) -> str:
        """Build a natural language request from a PlanStep."""
        parts = [step.title]
        if step.requirement:
            parts.append(f"需求：{step.requirement}")
        if step.approach:
            parts.append(f"实现思路：{step.approach}")
        if step.commands:
            parts.append(f"涉及命令：{', '.join(step.commands)}")
        if step.subtasks:
            parts.append("子任务：")
            for st in step.subtasks:
                parts.append(f"  - {st.description}")
        return "\n".join(parts)

    @staticmethod
    def _build_result_summary(results: list[dict[str, Any]]) -> str:
        """Build a text summary from task results."""
        commands: list[str] = []
        for tr in results:
            result = tr.get("result", {})
            result_type = result.get("type", "")

            if result_type == "single_command":
                cmd_obj = result.get("command", {})
                if isinstance(cmd_obj, dict) and cmd_obj.get("command"):
                    commands.append(cmd_obj["command"])
            elif result_type == "project":
                for phase in result.get("phases", []):
                    for task in phase.get("tasks", []):
                        for block in task.get("command_blocks", []):
                            if block.get("command"):
                                commands.append(block["command"])

        if commands:
            return f"生成了 {len(commands)} 条命令: {'; '.join(commands[:5])}" + (
                f" 等{len(commands)}条" if len(commands) > 5 else ""
            )
        return "步骤执行完成"

    @staticmethod
    def _build_command_layout_text(results: list[dict[str, Any]]) -> str:
        """Build a text description of generated commands for WriteAgent."""
        lines: list[str] = []
        for tr in results:
            result = tr.get("result", {})
            result_type = result.get("type", "")
            desc = tr.get("description", "")

            if result_type == "single_command":
                cmd_obj = result.get("command", {})
                if isinstance(cmd_obj, dict) and cmd_obj.get("command"):
                    lines.append(f"- {desc}: `{cmd_obj['command']}`")
            elif result_type == "project":
                for phase in result.get("phases", []):
                    for task in phase.get("tasks", []):
                        for block in task.get("command_blocks", []):
                            if block.get("command"):
                                btype = block.get("type", "chain")
                                lines.append(f"- [{btype}] `{block['command']}`")

        return "\n".join(lines) if lines else "（无命令）"

    def get_build_state(self, project_id: str) -> BuildState | None:
        """Get the active build state."""
        return self._active_builds.get(project_id)

    def _cleanup_expired(self) -> None:
        """Remove expired build states."""
        expired = [
            pid for pid, state in self._active_builds.items()
            if state.is_expired()
        ]
        for pid in expired:
            del self._active_builds[pid]
            logger.info("Cleaned up expired build state: %s", pid)


def _sse(event: str, data: dict[str, Any]) -> dict[str, Any]:
    """Build an SSE event dict."""
    return {"event": event, "data": data}


def _regex_mark_step_done(
    md_content: str,
    step_index: int,
    summary: str,
    command_layout: str = "",
) -> str:
    """Mark a build step as done in PROJECT.md using pure regex (no LLM).

    - Replaces ``## 步骤 N: … [ ]`` → ``## 步骤 N: … [x]``
    - Replaces ``- [ ]`` → ``- [x]`` within the step section
    - Appends ``**执行结果**: …`` (and optionally ``**命令布局**: …``) to the section

    This is the deterministic flag-on alternative to write_agent.mark_step_done.
    Lifted from WriteAgent._regex_mark_done and extended with layout support.
    """
    # Update step header: [ ] → [x]
    header_pattern = re.compile(
        rf"(##\s+步骤\s*{step_index}\s*[:：]\s*.+?)\s*\[\s*\]",
        re.MULTILINE,
    )
    md_content = header_pattern.sub(r"\1 [x]", md_content)

    # Find the step section boundaries
    step_header_re = re.compile(
        rf"^##\s+步骤\s*{step_index}\s*[:：]",
        re.MULTILINE,
    )
    next_header_re = re.compile(r"^##\s+步骤\s*\d+", re.MULTILINE)

    match = step_header_re.search(md_content)
    if match:
        start = match.start()
        next_match = next_header_re.search(md_content, match.end())
        end = next_match.start() if next_match else len(md_content)

        section = md_content[start:end]
        # Mark all subtasks done
        section = re.sub(r"- \[ \]", "- [x]", section)

        # Append execution result if not already present
        if "**执行结果**" not in section:
            section = section.rstrip() + f"\n**执行结果**: {summary}\n"

        # Optionally append command layout block
        if command_layout and "**命令布局**" not in section:
            section = section.rstrip() + f"\n**命令布局**:\n{command_layout}\n\n"
        else:
            section = section.rstrip() + "\n\n"

        md_content = md_content[:start] + section + md_content[end:]

    return md_content


# Singleton
build_orchestrator = BuildOrchestrator()
