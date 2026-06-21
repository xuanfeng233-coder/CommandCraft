"""Planner schemas — Pydantic v2 models for typed Decomposition + 图校验.

Pure functions, no I/O, no external deps beyond pydantic.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TaskDef(BaseModel):
    """Single task definition with aliases that match the LLM prompt's legacy JSON keys."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="task_id")
    title: str = Field("", alias="description")
    instruction: str = Field("", alias="user_request")
    recommended_commands: list[str] = []
    output_type: Literal[
        "simple_command", "execute_chain", "rawtext", "selector", "project"
    ] = "simple_command"
    execution_mode: Literal["once", "continuous"] = "continuous"
    depends_on: list[str] = []


class Decomposition(BaseModel):
    """Top-level decomposition result."""

    project_name: str = ""
    overview: str = ""
    is_single_task: bool = False
    tasks: list[TaskDef] = []


# ---------------------------------------------------------------------------
# Graph error
# ---------------------------------------------------------------------------


class GraphError(ValueError):
    """Raised when the task dependency graph is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------------------
# validate_graph
# ---------------------------------------------------------------------------


def validate_graph(d: Decomposition) -> None:
    """Validate the task dependency graph in d.

    Checks in order:
    1. All task ids are unique.
    2. No task id is empty.
    3. All depends_on references point to existing task ids.
    4. The graph is acyclic (Kahn topological sort).
    5. No task depends on itself.

    Raises GraphError with a precise Chinese message on the first violation.
    Returns None on success (also valid for an empty task list).
    """
    tasks = d.tasks

    # Empty graph is always valid.
    if not tasks:
        return None

    # ① Unique ids
    seen_ids: set[str] = set()
    for task in tasks:
        if task.id in seen_ids:
            raise GraphError(f"任务 id 重复：'{task.id}'")
        seen_ids.add(task.id)

    # ② Non-empty ids
    for task in tasks:
        if not task.id:
            raise GraphError("任务 id 不能为空")

    id_set = {task.id for task in tasks}

    # ③ depends_on references must exist
    for task in tasks:
        for dep in task.depends_on:
            if dep not in id_set:
                raise GraphError(f"任务 '{task.id}' 依赖了不存在的 task_id：'{dep}'")

    # ④ No self-dependency — check before Kahn so self-loops get the
    #    dedicated "自依赖" message rather than the generic cycle message.
    for task in tasks:
        if task.id in task.depends_on:
            raise GraphError(f"任务 '{task.id}' 依赖了自身（自依赖）")

    # ⑤ No cycles (Kahn topological sort)
    # Build in-degree map and adjacency list (edges: dep → task)
    in_degree: dict[str, int] = {task.id: 0 for task in tasks}
    children: dict[str, list[str]] = {task.id: [] for task in tasks}
    for task in tasks:
        for dep in task.depends_on:
            in_degree[task.id] += 1
            children[dep].append(task.id)

    queue: deque[str] = deque(tid for tid, deg in in_degree.items() if deg == 0)
    visited_count = 0
    while queue:
        tid = queue.popleft()
        visited_count += 1
        for child in children[tid]:
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    if visited_count != len(tasks):
        cycle_ids = [tid for tid, deg in in_degree.items() if deg > 0]
        raise GraphError(f"任务依赖图存在循环：涉及 task_id {cycle_ids}")

    return None


# ---------------------------------------------------------------------------
# to_legacy_decomposition
# ---------------------------------------------------------------------------


def to_legacy_decomposition(d: Decomposition, *, original_input: str) -> dict[str, Any]:
    """Convert a Decomposition to the legacy dict shape consumed by TaskManager.

    Each task is serialised with model_dump(by_alias=True) so the canonical
    Python names (id, title, instruction) map back to the legacy JSON keys
    (task_id, description, user_request).

    The returned dict mirrors the shape that MainAgent.decompose() used to
    produce and that TaskManager expects.
    """
    legacy_tasks = []
    for task in d.tasks:
        dumped = task.model_dump(by_alias=True)
        legacy_tasks.append(dumped)

    return {
        "project_name": d.project_name,
        "overview": d.overview,
        "is_single_task": d.is_single_task,
        "tasks": legacy_tasks,
        # _original_input is carried through for downstream consumers that need
        # the raw user text (e.g. TaskAgent context injection, _resume_task).
        "_original_input": original_input,
    }
