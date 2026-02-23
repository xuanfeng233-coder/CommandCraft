"""Orchestrator — parallel TaskAgent architecture.

Pipeline:
  Phase 1: Main Agent decompose (single LLM call)
  Phase 2: TaskAgent tier-based execution (parallel within tier, sequential across tiers)
  Phase 3: Main Agent summarize (single LLM call, multi-task only)

Post-processing: CommandValidator, StructuralValidator, CommandBlockLayout, OutputFormatter
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncGenerator

from backend.agents.main_agent import MainAgent
from backend.agents.task_agent import TaskAgent
from backend.config import (
    MAX_PARALLEL_TASKS,
    MAX_VALIDATION_RETRIES,
    SESSION_STATE_TTL,
)
from backend.skills.command_block_layout import command_block_layout
from backend.skills.command_validator import command_validator
from backend.skills.output_formatter import output_formatter
from backend.skills.structural_validator import structural_validator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TaskManager — manages parallel execution of tasks within a single request
# ---------------------------------------------------------------------------

class TaskManager:
    """Manages tier-based TaskAgent execution for one decomposition.

    Tasks are grouped into tiers via topological sort on depends_on.
    Within each tier, tasks run in parallel. Tiers run sequentially.
    """

    def __init__(self, decomposition: dict[str, Any]) -> None:
        self.decomposition = decomposition
        self.tasks: list[dict[str, Any]] = decomposition.get("tasks", [])
        self.task_states: dict[str, dict[str, Any]] = {}
        self._event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._completed_results: dict[str, dict[str, Any]] = {}
        self.created_at = time.time()

    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > SESSION_STATE_TTL

    def all_completed(self) -> bool:
        """Check if all tasks are completed (or failed)."""
        for task_def in self.tasks:
            tid = task_def.get("task_id", "")
            state = self.task_states.get(tid, {})
            status = state.get("status", "pending")
            if status not in ("completed", "failed"):
                return False
        return True

    def has_pending_work(self) -> bool:
        """Check if there are blocked or pending tasks that could still run."""
        for task_def in self.tasks:
            tid = task_def.get("task_id", "")
            state = self.task_states.get(tid, {})
            status = state.get("status", "pending")
            if status in ("pending", "blocked"):
                return True
        return False

    def get_completed_results(self) -> list[dict[str, Any]]:
        """Get all completed task results for summarization."""
        results = []
        for task_def in self.tasks:
            tid = task_def.get("task_id", "")
            state = self.task_states.get(tid, {})
            if state.get("status") == "completed":
                results.append({
                    "task_id": tid,
                    "description": task_def.get("description", ""),
                    "execution_mode": task_def.get("execution_mode", "continuous"),
                    "result": state.get("result", {}),
                })
        return results

    # ----- Tier computation (topological sort) -----

    def _compute_tiers(self) -> list[list[dict[str, Any]]]:
        """Group tasks into execution tiers via topological sort.

        Tier 0: tasks with no dependencies
        Tier N: tasks whose dependencies are all in tiers < N
        """
        task_map = {td.get("task_id", ""): td for td in self.tasks}
        assigned: dict[str, int] = {}  # task_id → tier number
        tiers: list[list[dict[str, Any]]] = []

        remaining = set(task_map.keys())

        while remaining:
            # Find tasks whose dependencies are all assigned
            current_tier: list[dict[str, Any]] = []
            for tid in list(remaining):
                deps = task_map[tid].get("depends_on", [])
                if all(d in assigned for d in deps):
                    current_tier.append(task_map[tid])
                    assigned[tid] = len(tiers)

            if not current_tier:
                # Cycle detected — force remaining into this tier
                logger.warning(
                    "Cycle detected in task dependencies, forcing remaining: %s",
                    remaining,
                )
                for tid in remaining:
                    current_tier.append(task_map[tid])
                    assigned[tid] = len(tiers)

            for td in current_tier:
                remaining.discard(td.get("task_id", ""))

            tiers.append(current_tier)

        return tiers

    # ----- Tier-based execution -----

    async def execute_all(self) -> AsyncGenerator[dict[str, Any], None]:
        """Execute tasks tier by tier: parallel within tier, sequential across tiers."""
        tiers = self._compute_tiers()

        for tier_idx, tier_tasks in enumerate(tiers):
            if not tier_tasks:
                continue

            logger.info(
                "Executing tier %d with %d task(s): %s",
                tier_idx, len(tier_tasks),
                [t.get("task_id") for t in tier_tasks],
            )

            # Inject predecessor context for dependent tasks
            for td in tier_tasks:
                self._inject_predecessor_context(td)

            # Execute tier tasks in parallel
            async for event in self._execute_tier(tier_tasks):
                yield event

            # Check if any tasks in this tier paused or failed
            tier_ids = {td.get("task_id", "") for td in tier_tasks}
            has_blocker = False
            for tid in tier_ids:
                status = self.task_states.get(tid, {}).get("status", "pending")
                if status in ("paused", "failed"):
                    has_blocker = True
                    break

            if has_blocker:
                # Mark downstream tasks as blocked
                self._mark_downstream_blocked(tier_ids, tiers, tier_idx)
                break  # Stop processing further tiers

    async def _execute_tier(
        self, tier_tasks: list[dict[str, Any]],
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Execute a single tier of tasks in parallel."""
        semaphore = asyncio.Semaphore(MAX_PARALLEL_TASKS)
        agent = TaskAgent()

        async def run_task(task_def: dict[str, Any]) -> None:
            tid = task_def.get("task_id", "")
            async with semaphore:
                try:
                    async for event in agent.execute(task_def):
                        if event.get("event") == "task_update":
                            data = event.get("data", {})
                            self.task_states[tid] = data
                            if data.get("status") == "completed":
                                self._completed_results[tid] = data.get("result", {})
                        await self._event_queue.put(event)
                except Exception as e:
                    logger.error("TaskAgent %s crashed: %s", tid, e)
                    error_event = {
                        "event": "task_update",
                        "data": {"task_id": tid, "status": "failed", "error": str(e)},
                    }
                    self.task_states[tid] = error_event["data"]
                    await self._event_queue.put(error_event)

        tasks_coros = [run_task(td) for td in tier_tasks]
        gather_task = asyncio.ensure_future(
            asyncio.gather(*tasks_coros, return_exceptions=True)
        )

        while True:
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=0.1)
                yield event
            except asyncio.TimeoutError:
                if gather_task.done():
                    while not self._event_queue.empty():
                        yield self._event_queue.get_nowait()
                    break

        if gather_task.done() and gather_task.exception():
            logger.error("Tier gather exception: %s", gather_task.exception())

    # ----- Dependency helpers -----

    def _inject_predecessor_context(self, task_def: dict[str, Any]) -> None:
        """Inject completed predecessor results into the task's user_request."""
        deps = task_def.get("depends_on", [])
        if not deps:
            return

        context_parts: list[str] = []
        for dep_id in deps:
            dep_result = self._completed_results.get(dep_id)
            if not dep_result:
                continue

            result_type = dep_result.get("type", "")
            # Find the description of the predecessor task
            dep_desc = ""
            for td in self.tasks:
                if td.get("task_id") == dep_id:
                    dep_desc = td.get("description", "")
                    break

            if result_type == "single_command":
                cmd_obj = dep_result.get("command", {})
                cmd_str = cmd_obj.get("command", "") if isinstance(cmd_obj, dict) else ""
                explanation = cmd_obj.get("explanation", "") if isinstance(cmd_obj, dict) else ""
                context_parts.append(
                    f"前置任务 {dep_id}（{dep_desc}）已生成命令：{cmd_str}"
                )
                if explanation:
                    context_parts.append(f"说明：{explanation}")
            elif result_type == "project":
                # Summarize project commands
                cmds: list[str] = []
                for phase in dep_result.get("phases", []):
                    for task in phase.get("tasks", []):
                        for block in task.get("command_blocks", []):
                            c = block.get("command", "")
                            if c:
                                cmds.append(c)
                context_parts.append(
                    f"前置任务 {dep_id}（{dep_desc}）已生成命令：{'; '.join(cmds)}"
                )

        if context_parts:
            predecessor_text = "\n".join(context_parts)
            task_def["user_request"] = (
                f"{task_def['user_request']}\n\n## 前置任务结果\n{predecessor_text}"
            )

    def _mark_downstream_blocked(
        self,
        blocker_ids: set[str],
        tiers: list[list[dict[str, Any]]],
        current_tier_idx: int,
    ) -> None:
        """Mark tasks in later tiers as blocked if they depend on blockers."""
        # Collect all task IDs that are paused/failed (direct blockers)
        failed_or_paused = set()
        for tid in blocker_ids:
            status = self.task_states.get(tid, {}).get("status", "")
            if status in ("paused", "failed"):
                failed_or_paused.add(tid)

        if not failed_or_paused:
            return

        # Walk remaining tiers and mark tasks whose deps intersect with blockers
        blocked_ids = set(failed_or_paused)
        for tier in tiers[current_tier_idx + 1:]:
            for td in tier:
                tid = td.get("task_id", "")
                deps = set(td.get("depends_on", []))
                if deps & blocked_ids:
                    blocked_ids.add(tid)
                    self.task_states[tid] = {"task_id": tid, "status": "blocked"}
                    self._event_queue.put_nowait({
                        "event": "task_update",
                        "data": {"task_id": tid, "status": "blocked"},
                    })

    # ----- Resume + unblock -----

    async def resume_task(
        self,
        task_id: str,
        user_answer: str,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Resume a paused task with user's answer, then execute unblocked downstream."""
        # Find the task definition
        task_def = None
        for td in self.tasks:
            if td.get("task_id") == task_id:
                task_def = dict(td)  # shallow copy
                break

        if not task_def:
            yield {
                "event": "error",
                "data": {"message": f"Task {task_id} not found"},
            }
            return

        # Append user answer to the request
        task_def["user_request"] = (
            f"{task_def['user_request']}\n\n用户补充信息：{user_answer}"
        )

        agent = TaskAgent()
        async for event in agent.execute(task_def):
            if event.get("event") == "task_update":
                data = event.get("data", {})
                self.task_states[task_id] = data
                if data.get("status") == "completed":
                    self._completed_results[task_id] = data.get("result", {})
            yield event

        # After resuming, try to execute newly unblocked downstream tasks
        async for event in self._execute_unblocked():
            yield event

    async def _execute_unblocked(self) -> AsyncGenerator[dict[str, Any], None]:
        """Find and execute tasks that were blocked but are now unblocked."""
        while True:
            newly_ready: list[dict[str, Any]] = []
            for td in self.tasks:
                tid = td.get("task_id", "")
                state = self.task_states.get(tid, {})
                status = state.get("status", "pending")

                if status not in ("blocked", "pending"):
                    continue

                # Check if all dependencies are now completed
                deps = td.get("depends_on", [])
                if not deps:
                    # No deps — was just pending, not blocked
                    if status == "pending":
                        newly_ready.append(td)
                    continue

                all_deps_done = all(
                    self.task_states.get(d, {}).get("status") == "completed"
                    for d in deps
                )
                if all_deps_done:
                    newly_ready.append(td)

            if not newly_ready:
                break

            logger.info(
                "Unblocked %d task(s): %s",
                len(newly_ready),
                [t.get("task_id") for t in newly_ready],
            )

            # Inject predecessor context and execute
            for td in newly_ready:
                self._inject_predecessor_context(td)

            async for event in self._execute_tier(newly_ready):
                yield event

            # Check if any paused/failed — stop further unblocking
            has_blocker = False
            for td in newly_ready:
                tid = td.get("task_id", "")
                status = self.task_states.get(tid, {}).get("status", "")
                if status in ("paused", "failed"):
                    has_blocker = True
                    break

            if has_blocker:
                break


# ---------------------------------------------------------------------------
# Orchestrator — main entry point
# ---------------------------------------------------------------------------

class Orchestrator:
    """Parallel TaskAgent orchestrator with tier-based dependency execution.

    SSE event contract:
        event: thinking      → {"text": "..."}
        event: task_list     → {"project_name", "overview", "tasks": [{task_id, description, status}]}
        event: task_update   → {"task_id", "status", "result?", "questions?", "error?"}
        event: task_thinking → {"task_id", "text"}
        event: summary       → {"type", "commands[]", "explanation", "command_blocks[]", "project?"}
        event: content       → {"type": "single_command|conversation|project", ...}  (for backward compat)
        event: done          → {"session_id?"}
        event: error         → {"message"}
    """

    def __init__(self) -> None:
        self.main_agent = MainAgent()
        self._active_sessions: dict[str, TaskManager] = {}

    async def process_message_stream(
        self,
        user_input: str,
        session_context: str = "",
        session_id: str = "",
        task_id: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Process a user message and yield SSE events.

        Args:
            user_input: The user's message text.
            session_context: Conversation history for context.
            session_id: Session identifier for state management.
            task_id: If set, route the answer to a specific paused task.
        """
        # Clean up expired sessions
        self._cleanup_expired()

        # --- Case A: Resuming a paused task ---
        if task_id and session_id in self._active_sessions:
            async for event in self._resume_task(
                session_id, task_id, user_input,
            ):
                yield event
            return

        # --- Case B: New message with active session → cancel old, start fresh ---
        if session_id in self._active_sessions:
            del self._active_sessions[session_id]

        # --- Case C: New request → pipeline ---

        # Phase 1: Main Agent decompose
        yield {"event": "thinking", "data": {"text": "正在分析您的需求...\n"}}

        decomposition = await self.main_agent.decompose(
            user_input, session_context,
        )

        thinking = decomposition.pop("_thinking", "")
        if thinking:
            yield {"event": "thinking", "data": {"text": thinking}}

        tasks = decomposition.get("tasks", [])
        is_single = decomposition.get("is_single_task", len(tasks) <= 1)

        if not tasks:
            yield {
                "event": "content",
                "data": {
                    "type": "conversation",
                    "message": "抱歉，我无法理解您的需求。请尝试更详细地描述。",
                    "questions": [],
                },
            }
            yield {"event": "done", "data": {}}
            return

        # Emit task list (with depends_on and initial blocked status)
        has_deps = any(t.get("depends_on") for t in tasks)
        yield {
            "event": "task_list",
            "data": {
                "project_name": decomposition.get("project_name", ""),
                "overview": decomposition.get("overview", ""),
                "tasks": [
                    {
                        "task_id": t.get("task_id", str(i + 1)),
                        "description": t.get("description", f"任务 {i + 1}"),
                        "depends_on": t.get("depends_on", []),
                        "status": "blocked" if t.get("depends_on") else "pending",
                    }
                    for i, t in enumerate(tasks)
                ],
            },
        }

        # Phase 2: TaskAgent tier-based execution
        if has_deps:
            yield {"event": "thinking", "data": {"text": f"正在按依赖顺序执行 {len(tasks)} 个任务...\n"}}
        else:
            yield {"event": "thinking", "data": {"text": f"正在并行执行 {len(tasks)} 个任务...\n"}}

        mgr = TaskManager(decomposition)
        if session_id:
            self._active_sessions[session_id] = mgr

        async for event in mgr.execute_all():
            yield event

        # Check if any tasks are paused
        if not mgr.all_completed():
            # Some tasks are paused — keep manager alive, emit done
            yield {"event": "done", "data": {}}
            return

        # Phase 3: Summarize (only for multi-task)
        completed_results = mgr.get_completed_results()

        if is_single and len(completed_results) == 1:
            # Single task — emit result directly
            result = completed_results[0].get("result", {})
            result_type = result.get("type", "")

            if result_type == "project":
                result = self._post_process_project(result)
            elif result_type == "single_command":
                retried = await self._structural_validate_and_retry_simple(
                    result, user_input,
                )
                if retried is not None:
                    result = retried

            formatted = output_formatter.format_result(result)
            yield {"event": "content", "data": formatted}
        else:
            # Multi-task — LLM summarize
            yield {"event": "thinking", "data": {"text": "正在汇总所有任务结果...\n"}}

            summary = await self.main_agent.summarize(user_input, completed_results)
            summary_thinking = summary.pop("_thinking", "")
            if summary_thinking:
                yield {"event": "thinking", "data": {"text": summary_thinking}}

            # Build project data from summary
            project_data = self._build_project_from_summary(
                decomposition, summary, completed_results,
            )

            # Post-process (layout + validation)
            project_data = self._post_process_project(project_data)

            formatted = output_formatter.format_result(project_data)
            yield {"event": "content", "data": formatted}

        # Clean up session state
        if session_id in self._active_sessions:
            del self._active_sessions[session_id]

        yield {"event": "done", "data": {}}

    # ----- Resume paused task -----

    async def _resume_task(
        self,
        session_id: str,
        task_id: str,
        user_answer: str,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Resume a specific paused task with user's answer."""
        mgr = self._active_sessions.get(session_id)
        if not mgr:
            yield {
                "event": "error",
                "data": {"message": "Session not found"},
            }
            return

        logger.info(
            "Resuming task %s in session %s with answer: %s",
            task_id, session_id, user_answer[:80],
        )

        async for event in mgr.resume_task(task_id, user_answer):
            yield event

        # Check if all tasks now completed (or no more work to do)
        if mgr.all_completed():
            decomposition = mgr.decomposition
            is_single = decomposition.get("is_single_task", False)
            completed_results = mgr.get_completed_results()

            if is_single and len(completed_results) == 1:
                result = completed_results[0].get("result", {})
                result_type = result.get("type", "")

                if result_type == "project":
                    result = self._post_process_project(result)
                elif result_type == "single_command":
                    retried = await self._structural_validate_and_retry_simple(
                        result, user_answer,
                    )
                    if retried is not None:
                        result = retried

                formatted = output_formatter.format_result(result)
                yield {"event": "content", "data": formatted}
            else:
                yield {"event": "thinking", "data": {"text": "正在汇总所有任务结果...\n"}}

                user_input = decomposition.get("_original_input", user_answer)
                summary = await self.main_agent.summarize(
                    user_input, completed_results,
                )
                summary.pop("_thinking", "")

                project_data = self._build_project_from_summary(
                    decomposition, summary, completed_results,
                )
                project_data = self._post_process_project(project_data)

                formatted = output_formatter.format_result(project_data)
                yield {"event": "content", "data": formatted}

            # Clean up
            if session_id in self._active_sessions:
                del self._active_sessions[session_id]

        yield {"event": "done", "data": {}}

    # ----- Post-processing -----

    def _post_process_project(self, project_data: dict[str, Any]) -> dict[str, Any]:
        """Post-process project results: add layout + validate commands."""
        thinking = project_data.get("thinking")

        project_obj = project_data.get("project", project_data)
        try:
            layout_result = command_block_layout.generate_layout(project_obj)
            project_obj["layout"] = layout_result["layout"]
            project_obj["groups"] = layout_result["groups"]
            project_obj["dimensions"] = layout_result["dimensions"]
        except Exception as e:
            logger.warning("CommandBlockLayout failed: %s", e)

        all_commands: list[str] = []
        for phase in project_obj.get("phases", []):
            for task in phase.get("tasks", []):
                for block in task.get("command_blocks", []):
                    cmd = block.get("command", "")
                    if cmd:
                        all_commands.append(cmd)

        if all_commands:
            try:
                results = command_validator.validate(all_commands)
                error_count = sum(1 for r in results if not r.get("valid", True))
                project_obj["validation_summary"] = {
                    "total_commands": len(all_commands),
                    "errors": error_count,
                    "valid": error_count == 0,
                }
            except Exception as e:
                logger.warning("Project validation failed: %s", e)

        result = {"type": "project", **project_obj}
        if thinking:
            result["thinking"] = thinking
        return result

    @staticmethod
    def _run_validation(content_data: dict[str, Any]) -> None:
        """Run CommandValidator and merge results into content_data."""
        command_obj = content_data.get("command")
        if not command_obj or not isinstance(command_obj, dict):
            return
        cmd_str = command_obj.get("command", "")
        if not cmd_str:
            return

        cmd_lines = [line.strip() for line in cmd_str.split("\n") if line.strip()]
        try:
            results = command_validator.validate(cmd_lines)
            if not results:
                return

            all_errors = []
            all_warnings = []
            all_valid = True

            for validation in results:
                errors = validation.get("errors", [])
                warnings_list = [w["message"] for w in validation.get("warnings", [])]
                if errors:
                    all_valid = False
                    for err in errors:
                        all_errors.append(
                            f"[{err['type']}] {err['message']} — {err.get('suggestion', '')}"
                        )
                all_warnings.extend(warnings_list)

            existing = command_obj.get("warnings") or []
            existing.extend(all_errors)
            existing.extend(all_warnings)
            if existing:
                command_obj["warnings"] = existing

            command_obj["validation"] = {
                "valid": all_valid,
                "error_count": len(all_errors),
            }
        except Exception as e:
            logger.warning("CommandValidator failed: %s", e)

    async def _structural_validate_and_retry_simple(
        self,
        content_data: dict[str, Any],
        user_input: str,
    ) -> dict[str, Any] | None:
        """Run structural validation on a single_command result.

        Returns replacement on successful retry, or None to keep original.
        """
        commands = self._extract_commands_for_validation(content_data)
        if not commands:
            return None

        results = structural_validator.validate(commands)
        if not structural_validator.has_errors(results):
            self._attach_validation_warnings(content_data, results)
            return None

        error_count = sum(len(r.errors) for r in results if not r.valid)
        logger.info(
            "Structural validation found %d error(s), retrying TaskAgent…",
            error_count,
        )

        if MAX_VALIDATION_RETRIES < 1:
            self._attach_validation_warnings(content_data, results)
            return None

        # Retry via TaskAgent with validation feedback
        feedback = structural_validator.format_feedback(results)
        retry_request = f"{user_input}\n\n{feedback}"

        agent = TaskAgent()
        task_def = {
            "task_id": "retry",
            "user_request": retry_request,
            "recommended_commands": [],
            "output_type": "simple_command",
        }

        new_result = None
        async for event in agent.execute(task_def):
            if event.get("event") == "task_update":
                data = event.get("data", {})
                if data.get("status") == "completed":
                    new_result = data.get("result")

        if new_result:
            new_commands = self._extract_commands_for_validation(new_result)
            if new_commands:
                new_results = structural_validator.validate(new_commands)
                self._attach_validation_warnings(new_result, new_results)
                if not structural_validator.has_errors(new_results):
                    logger.info("Retry succeeded — using corrected result")
                    return new_result

        self._attach_validation_warnings(content_data, results)
        return None

    @staticmethod
    def _extract_commands_for_validation(content_data: dict[str, Any]) -> list[str]:
        """Extract command strings from content_data."""
        result_type = content_data.get("type", "")
        commands: list[str] = []

        if result_type == "single_command":
            cmd_obj = content_data.get("command")
            if isinstance(cmd_obj, dict):
                cmd_str = cmd_obj.get("command", "")
                if cmd_str:
                    for line in cmd_str.split("\n"):
                        line = line.strip()
                        if line:
                            commands.append(line)

        elif result_type == "project":
            for phase in content_data.get("phases", []):
                for task in phase.get("tasks", []):
                    for block in task.get("command_blocks", []):
                        cmd = block.get("command", "")
                        if cmd:
                            commands.append(cmd)

        return commands

    @staticmethod
    def _attach_validation_warnings(
        content_data: dict[str, Any],
        results: list,
    ) -> None:
        """Attach structural validation warnings/errors."""
        result_type = content_data.get("type", "")

        if result_type == "single_command":
            cmd_obj = content_data.get("command")
            if isinstance(cmd_obj, dict):
                existing = cmd_obj.get("warnings") or []
                for r in results:
                    for e in r.errors:
                        msg = f"[structural/{e.type}] {e.message}"
                        if e.suggestion:
                            msg += f" — {e.suggestion}"
                        existing.append(msg)
                    for w in r.warnings:
                        existing.append(f"[structural] {w}")
                if existing:
                    cmd_obj["warnings"] = existing

        elif result_type == "project":
            structural_errors: list[str] = []
            for r in results:
                for e in r.errors:
                    structural_errors.append(
                        f"[{e.type}] {e.message} — {r.command}"
                    )
            if structural_errors:
                summary = content_data.get("validation_summary") or {}
                summary["structural_errors"] = structural_errors
                content_data["validation_summary"] = summary

    def _build_project_from_summary(
        self,
        decomposition: dict[str, Any],
        summary: dict[str, Any],
        completed_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build a project data structure from summarization result.

        If the summary provides phases with command_blocks, use those.
        Otherwise, fall back to building phases from task results.
        """
        phases = summary.get("phases", [])

        # If summary provided valid phases with command_blocks, use them
        if phases and any(
            block
            for p in phases
            for t in p.get("tasks", [])
            for block in t.get("command_blocks", [])
        ):
            return {
                "type": "project",
                "project_name": decomposition.get("project_name", ""),
                "overview": summary.get("explanation", decomposition.get("overview", "")),
                "phases": phases,
            }

        # Fallback: build phases from completed results
        fallback_phases = []
        for cr in completed_results:
            result = cr.get("result", {})
            result_type = result.get("type", "")
            tid = cr.get("task_id", "")
            desc = cr.get("description", "")
            mode = cr.get("execution_mode", "continuous")

            if result_type == "single_command":
                cmd_obj = result.get("command", {})
                cmd_str = cmd_obj.get("command", "") if isinstance(cmd_obj, dict) else ""
                cmd_lines = [l.strip() for l in cmd_str.split("\n") if l.strip()]
                blocks = self._command_lines_to_blocks(cmd_lines, mode)

                explanation = ""
                if isinstance(cmd_obj, dict):
                    explanation = cmd_obj.get("explanation", "")

                fallback_phases.append({
                    "phase_name": desc,
                    "description": explanation or desc,
                    "tasks": [{
                        "task_id": tid,
                        "description": desc,
                        "commands": [l.split()[0].lstrip("/") for l in cmd_lines if l],
                        "command_blocks": blocks,
                        "dependencies": [],
                    }],
                })

            elif result_type == "project":
                inner_phases = result.get("phases", [])
                fallback_phases.extend(inner_phases)

        return {
            "type": "project",
            "project_name": decomposition.get("project_name", ""),
            "overview": summary.get("explanation", decomposition.get("overview", "")),
            "phases": fallback_phases,
        }

    @staticmethod
    def _command_lines_to_blocks(
        cmd_lines: list[str],
        execution_mode: str,
    ) -> list[dict[str, Any]]:
        """Convert command lines to command_block entries."""
        if not cmd_lines:
            return []

        blocks: list[dict[str, Any]] = []
        for i, line in enumerate(cmd_lines):
            if i == 0:
                if execution_mode == "continuous":
                    block_type = "repeating"
                    needs_redstone = False
                else:
                    block_type = "impulse"
                    needs_redstone = True
            else:
                block_type = "chain"
                needs_redstone = False

            blocks.append({
                "type": block_type,
                "conditional": False,
                "needs_redstone": needs_redstone,
                "command": line,
                "comment": "",
            })

        return blocks

    def _cleanup_expired(self) -> None:
        """Remove expired session states."""
        expired = [
            sid for sid, mgr in self._active_sessions.items()
            if mgr.is_expired()
        ]
        for sid in expired:
            del self._active_sessions[sid]
            logger.info("Cleaned up expired session state: %s", sid)


# Singleton
orchestrator = Orchestrator()
