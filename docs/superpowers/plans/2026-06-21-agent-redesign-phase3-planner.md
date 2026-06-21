# Phase 3 — Typed Planner + 多任务统一循环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 typed `Planner`（Pydantic `Decomposition`/`TaskDef` + 图校验 + 有界修复 + 区分传输/解析失败、**取消静默降级**）替换 `MainAgent.decompose`；并把多任务路径瘦身为「每个任务跑统一 `AgentLoop`」（typed 前驱上下文），全部藏在 `USE_AGENT_LOOP` 后——flag-off 与今天的 `MainAgent+TaskManager+TaskAgent` 路径**逐字一致**。

**Architecture:** Phase 1/2 已交付 `backend/llm/`（韧性客户端 + 分类异常）、`backend/agentloop/`（schemas / ToolRegistry+7 工具 / AgentLoop / step Native&Prompted / single_task / build_default_registry），且 chat 单任务已走 AgentLoop。本期新增 `backend/agents/{planner_schemas,planner,task_result}.py`，并在 orchestrator 的 `TaskManager` 引入 `use_loop` 执行器接缝（`_run_via_agentloop`），保留分层并行调度。LLM 客户端**已**经 `with_retry` 抛 `Transient/PermanentLLMError`——Planner 不再加重试，只做 schema 修复。

**Tech Stack:** Python 3.11、Pydantic v2、asyncio；测试 pytest + pytest-asyncio。

## Global Constraints

- 语言：注释/docstring/面向用户字符串中文。
- **flag-off 逐字一致**：`USE_AGENT_LOOP=false` 时 `MainAgent.decompose` + `TaskManager`(TaskAgent) + `summarize` 路径不变；用 golden 事件序列 + `git diff` 自查。新分支只在 `USE_AGENT_LOOP` 真时触发。
- **不改 `backend/models/schemas.py`** 的 `TaskDefinition`/`DecompositionResult`（flag-off 与 output_formatter/build 仍用它）。新模型是 Planner 内部的，`to_legacy_decomposition` 是接缝，产出**与今天 decompose 相同的 dict 形状**给 TaskManager 消费。
- **复用大 decompose prompt 原样**（`main_agent.py` 的 `_DECOMPOSE_PROMPT`/`_DECOMPOSE_PROMPT_JAVA`）作 `Planner.PROMPT`；用 Pydantic `Field(alias=...)` + `populate_by_name=True` 让 `model_validate` 直接吃 prompt 输出的 legacy 键（`task_id`/`description`/`user_request`）。
- **传输 vs 解析**：`client.chat` 抛的 `LLMError`（已被 `with_retry` 重试过）原样向外传播——Planner **不 catch、不再重试**；仅「成功返回但 body 不合 schema」走有界修复（`max_repairs=2`）；修复耗尽抛 `PlannerParseError`，**绝不**返回假单任务。
- **预算**：Planner 最多 `1+max_repairs` 次 LLM 调用；不在修复循环外再包重试。
- 提交频繁，提交信息中文，结尾附 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。测试从仓库根 `.venv/bin/python -m pytest`，pristine。

---

## File Structure

**新建**
- `backend/agents/planner_schemas.py` — `TaskDef` / `Decomposition` / `GraphError` / `validate_graph` / `to_legacy_decomposition`
- `backend/agents/task_result.py` — `TaskResult` / `render_predecessor_block`
- `backend/agents/planner.py` — `Planner` / `PlannerParseError`
- `tests/agents/__init__.py`, `tests/orchestrator/__init__.py`（空）
- `tests/agents/test_planner_schemas.py` / `test_planner.py`
- `tests/agentloop/test_predecessor_context.py`
- `tests/orchestrator/test_multitask_loop.py` / `test_summarize_path.py` / `test_phase3_regression.py`

**修改**
- `backend/agentloop/single_task.py` — `build_single_task_messages` 加可选 `predecessors: list[TaskResult] | None`（向后兼容）
- `backend/orchestrator/orchestrator.py` — `Orchestrator.__init__` 加 `self.planner`；`process_message_stream` Phase1 按 flag 分支 + Planner 错误包装成 `error` 事件；`TaskManager(use_loop=)` + `_run_one` 接缝 + `_run_via_agentloop`；resume 走同接缝

---

## Task 1: Planner schemas + 图校验（纯函数）

**Files:** Create `backend/agents/planner_schemas.py`, `tests/agents/__init__.py`, `tests/agents/test_planner_schemas.py`

**Interfaces:**
```python
class TaskDef(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str = Field(alias="task_id")
    title: str = Field("", alias="description")
    instruction: str = Field("", alias="user_request")
    recommended_commands: list[str] = []
    output_type: Literal["simple_command","execute_chain","rawtext","selector","project"] = "simple_command"
    execution_mode: Literal["once","continuous"] = "continuous"
    depends_on: list[str] = []

class Decomposition(BaseModel):
    project_name: str = ""
    overview: str = ""
    is_single_task: bool = False
    tasks: list[TaskDef] = []

class GraphError(ValueError):
    def __init__(self, message: str): super().__init__(message); self.message = message

def validate_graph(d: Decomposition) -> None      # 违规抛 GraphError（中文 message）
def to_legacy_decomposition(d: Decomposition, *, original_input: str) -> dict[str, Any]
```
`validate_graph` 按序检查（每项精确中文 message）：① id 唯一 ② id 非空 ③ depends_on 引用存在 ④ 无环（Kahn 拓扑）⑤ 无自依赖。空 tasks 视为合法。
`to_legacy_decomposition` 用 `model_dump(by_alias=True)` 把每 task 转回 `{task_id, description, user_request, recommended_commands, output_type, execution_mode, depends_on}`，顶层带 `project_name/overview/is_single_task`，并补 legacy decompose 需要的字段（对照 `main_agent.py` decompose 输出 dict）。

- [ ] **Step 1: 写失败测试**

Create `tests/agents/__init__.py`（空）。Create `tests/agents/test_planner_schemas.py`:
```python
import pytest
from pydantic import ValidationError

from backend.agents.planner_schemas import (
    Decomposition, GraphError, TaskDef, to_legacy_decomposition, validate_graph,
)


def _decomp(tasks):
    return Decomposition(tasks=[TaskDef(**t) for t in tasks])


def test_valid_dag_passes_and_maps_legacy_keys():
    d = _decomp([
        {"task_id": "1", "description": "建场地", "user_request": "造平台", "depends_on": []},
        {"task_id": "2", "description": "加机关", "user_request": "放命令方块", "depends_on": ["1"]},
    ])
    assert validate_graph(d) is None
    legacy = to_legacy_decomposition(d, original_input="x")
    assert legacy["tasks"][0]["task_id"] == "1"
    assert legacy["tasks"][0]["user_request"] == "造平台"
    assert legacy["tasks"][1]["depends_on"] == ["1"]


def test_alias_accepts_prompt_json_keys():
    # prompt 产出 legacy 键，model_validate 直接吃
    d = Decomposition.model_validate({"tasks": [{"task_id": "1", "description": "d", "user_request": "u"}]})
    assert d.tasks[0].id == "1" and d.tasks[0].title == "d" and d.tasks[0].instruction == "u"


def test_duplicate_id_raises():
    d = _decomp([{"task_id": "1"}, {"task_id": "1"}])
    with pytest.raises(GraphError) as e:
        validate_graph(d)
    assert "1" in e.value.message


def test_missing_ref_raises_named():
    d = _decomp([{"task_id": "1", "depends_on": ["99"]}])
    with pytest.raises(GraphError) as e:
        validate_graph(d)
    assert "99" in e.value.message


def test_cycle_raises():
    d = _decomp([{"task_id": "1", "depends_on": ["2"]}, {"task_id": "2", "depends_on": ["1"]}])
    with pytest.raises(GraphError) as e:
        validate_graph(d)
    assert "循环" in e.value.message


def test_self_dep_raises():
    d = _decomp([{"task_id": "1", "depends_on": ["1"]}])
    with pytest.raises(GraphError):
        validate_graph(d)


def test_bad_enum_raises_validation_error():
    with pytest.raises(ValidationError):
        TaskDef(task_id="1", output_type="frobnicate")


def test_empty_tasks_valid():
    assert validate_graph(Decomposition(tasks=[])) is None
```

- [ ] **Step 2: 运行确认失败** → FAIL（模块不存在）。

- [ ] **Step 3: 实现** `backend/agents/planner_schemas.py`（按接口；Kahn 拓扑求残留节点作环 ids；`model_dump(by_alias=True)` 转 legacy）。

- [ ] **Step 4: 运行确认通过** → PASS（8 passed）。

- [ ] **Step 5: Commit**
```bash
git add backend/agents/planner_schemas.py tests/agents/__init__.py tests/agents/test_planner_schemas.py
git commit -m "feat(planner): Decomposition/TaskDef schemas + 图校验（唯一/无环/引用/自依赖）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Planner.plan()（LLM + 校验 + 有界修复 + 错误区分）

**Files:** Create `backend/agents/planner.py`, `tests/agents/test_planner.py`

**Interfaces:**
```python
class PlannerParseError(Exception): ...   # schema/JSON 修复耗尽（非传输错误）

class Planner:
    async def plan(self, user_input, session_context="", *, client=None,
                   edition="bedrock", max_repairs=2) -> tuple[Decomposition, str]:
        # 返回 (decomposition, thinking)
```
**控制流（关键）：** 先打开 `backend/agents/main_agent.py` 读 `decompose`（消息组装 `:414-424`）+ `_DECOMPOSE_PROMPT`/`_DECOMPOSE_PROMPT_JAVA`。Planner 复用 prompt（import 或拷贝引用）。循环 `1+max_repairs` 次：
- `resp = await (client or get_llm_client()).chat(msgs, max_tokens=DECOMPOSE_MAX_TOKENS, think=True)` —— **不 catch**，`LLMError` 向外传播（传输，已重试）。
- `data = BaseSkill.extract_json(content)`；`None` → 当作 schema 失败，repair message = "输出不是合法 JSON，请只输出一个 JSON 对象"。
- `try: d = Decomposition.model_validate(data); validate_graph(d); return (d, thinking)`
- `except (ValidationError, GraphError, TypeError) as e:` 追加 assistant 消息 + user 修复消息（含 **e 的确切文本** + "只输出修正后的 JSON 对象"），continue。
- 耗尽 → `raise PlannerParseError(str(last_error))`。

- [ ] **Step 1: 写失败测试**

Create `tests/agents/test_planner.py`:
```python
import pytest

from backend.agents.planner import Planner, PlannerParseError
from backend.llm.errors import PermanentLLMError, TransientLLMError

VALID = '{"is_single_task": false, "tasks": [{"task_id":"1","description":"d","user_request":"u","depends_on":[]},{"task_id":"2","description":"e","user_request":"v","depends_on":["1"]}]}'
CYCLE = '{"tasks":[{"task_id":"1","depends_on":["2"]},{"task_id":"2","depends_on":["1"]}]}'


class FakeClient:
    def __init__(self, script):
        self._script = script
        self.calls = 0
        self.last_messages = None

    async def chat(self, messages, *, max_tokens=None, think=None):
        self.last_messages = messages
        item = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return {"message": {"role": "assistant", "content": item, "thinking": "想"}}


async def test_happy_path_once():
    c = FakeClient([VALID])
    d, thinking = await Planner().plan("造个东西", client=c)
    assert [t.id for t in d.tasks] == ["1", "2"]
    assert thinking == "想"
    assert c.calls == 1


async def test_repair_once_then_clean():
    c = FakeClient([CYCLE, VALID])
    d, _ = await Planner().plan("x", client=c)
    assert [t.id for t in d.tasks] == ["1", "2"]
    assert c.calls == 2
    # 第二次调用的消息里含环错误反馈
    assert any("循环" in m.get("content", "") for m in c.last_messages)


async def test_repair_exhausted_raises_not_fallback():
    c = FakeClient([CYCLE, CYCLE, CYCLE])
    with pytest.raises(PlannerParseError):
        await Planner().plan("x", client=c, max_repairs=2)
    assert c.calls == 3  # 1 + 2


async def test_transport_transient_propagates_no_repair():
    c = FakeClient([TransientLLMError("net")])
    with pytest.raises(TransientLLMError):
        await Planner().plan("x", client=c)
    assert c.calls == 1  # 不进修复


async def test_transport_permanent_propagates():
    c = FakeClient([PermanentLLMError("auth")])
    with pytest.raises(PermanentLLMError):
        await Planner().plan("x", client=c)


async def test_non_json_then_json_repairs():
    c = FakeClient(["这是一段废话不是JSON", VALID])
    d, _ = await Planner().plan("x", client=c)
    assert len(d.tasks) == 2
    assert c.calls == 2
    assert any("JSON" in m.get("content", "") for m in c.last_messages)


async def test_java_edition_uses_java_prompt():
    c = FakeClient([VALID])
    await Planner().plan("x", client=c, edition="java")
    sys_content = c.last_messages[0]["content"]
    assert "Java" in sys_content or "/data" in sys_content
```

- [ ] **Step 2: 运行确认失败** → FAIL。

- [ ] **Step 3: 实现** `backend/agents/planner.py`（复用 `main_agent` 的 prompt 常量；`get_llm_client` from `backend.subscription.llm_context`；`BaseSkill.extract_json`）。

- [ ] **Step 4: 运行确认通过** → PASS（7 passed）。

- [ ] **Step 5: Commit**
```bash
git add backend/agents/planner.py tests/agents/test_planner.py
git commit -m "feat(planner): Planner.plan — 校验+有界修复+传输/解析错误区分（取消静默降级）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: typed 前驱上下文 TaskResult + 注入（parity 门槛）

**Files:** Create `backend/agents/task_result.py`, `tests/agentloop/test_predecessor_context.py`；Modify `backend/agentloop/single_task.py`

**Interfaces:**
```python
@dataclass
class TaskResult:
    task_id: str
    description: str
    result_type: Literal["single_command","project","conversation"]
    commands: list[str]
    explanation: str = ""
    user_answer: str = ""

def render_predecessor_block(deps: list[TaskResult]) -> str   # 与 legacy 串拼字节一致
def task_result_from_legacy(dep_id: str, completed: dict, user_answer: str = "") -> TaskResult
```
`build_single_task_messages` 加可选 `predecessors: list[TaskResult] | None = None`（默认 None → 与今天逐字一致）；非空时在 user 消息追加 `## 前置任务结果\n{render_predecessor_block(...)}`。

**背景（关键）：** 先打开 `backend/orchestrator/orchestrator.py` 读 `_inject_predecessor_context`（约 :243-300），把它产生的中文文本逻辑搬进 `render_predecessor_block`（**逐字**：用户回答行、"已生成命令"行、"说明"行、project 多块的 phase→task→block 展开顺序）。`task_result_from_legacy` 从 `_completed_results[dep]` 的 dict 形状抽 commands（single_command 与 project 两种）。

- [ ] **Step 1: 写失败测试**

Create `tests/agentloop/test_predecessor_context.py`：覆盖 ① single_command 带 explanation 的块 == legacy golden（从 orchestrator 逻辑构造期望串）② project 多块顺序 ③ 含 user_answer 的 resumed 块 ④ `build_single_task_messages(predecessors=None)` 与今天逐字一致（回归）⑤ `predecessors=[...]` 时 user 消息以 `## 前置任务结果` 结尾。
```python
from backend.agents.task_result import TaskResult, render_predecessor_block, task_result_from_legacy
from backend.agentloop.single_task import build_single_task_messages


def test_single_command_block_matches_legacy_golden():
    tr = TaskResult("1", "建场地", "single_command", ["/fill ~ ~ ~ ~ ~ ~ stone"], explanation="铺地")
    block = render_predecessor_block([tr])
    # golden 依 orchestrator._inject_predecessor_context 文案构造
    assert "前置任务 1" in block and "建场地" in block
    assert "/fill ~ ~ ~ ~ ~ ~ stone" in block
    assert "铺地" in block


def test_user_answer_block():
    tr = TaskResult("1", "确认", "conversation", [], user_answer="要钻石剑")
    block = render_predecessor_block([tr])
    assert "要钻石剑" in block


def test_predecessors_none_is_regression_identical():
    a = build_single_task_messages("x", "simple_command", "（目录）")
    b = build_single_task_messages("x", "simple_command", "（目录）", predecessors=None)
    assert a == b


def test_predecessors_appended():
    tr = TaskResult("1", "d", "single_command", ["/say hi"])
    msgs = build_single_task_messages("x", "simple_command", "", predecessors=[tr])
    assert any("## 前置任务结果" in m["content"] for m in msgs)
```
> 实现者：把 golden 文案对齐真实的 `_inject_predecessor_context` 输出（读源文件取确切措辞），断言关键子串与顺序；若能，构造完整 golden 串做 `==`。

- [ ] **Step 2: 运行确认失败** → FAIL。

- [ ] **Step 3: 实现** `task_result.py` + 改 `single_task.build_single_task_messages`（向后兼容新增关键字参数）。

- [ ] **Step 4: 运行确认通过 + 回归** → `.venv/bin/python -m pytest tests/ -q` 全绿（证明 single_task 既有调用不变）。

- [ ] **Step 5: Commit**
```bash
git add backend/agents/task_result.py backend/agentloop/single_task.py tests/agentloop/test_predecessor_context.py
git commit -m "feat(planner): typed 前驱上下文 TaskResult + 注入（与 legacy 串拼 parity）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: orchestrator 多任务接线（use_loop 接缝 + 错误事件）

**Files:** Modify `backend/orchestrator/orchestrator.py`；Create `tests/orchestrator/__init__.py`, `tests/orchestrator/test_multitask_loop.py`

**做法（关键）：** 先通读 `process_message_stream` + `TaskManager`。
1. `Orchestrator.__init__` 加 `self.planner = Planner()`。
2. `process_message_stream` Phase1 按 flag 分支（包错误）：
```python
if USE_AGENT_LOOP:
    try:
        decomp, thinking = await self.planner.plan(user_input, session_context, edition=edition)
    except (PlannerParseError, LLMError) as e:
        yield {"event": "error", "data": {"message": f"任务分解失败：{e}"}}
        yield {"event": "done", "data": {}}
        return
    decomposition = to_legacy_decomposition(decomp, original_input=user_input)
else:
    decomposition = await self.main_agent.decompose(user_input, session_context, edition=edition)
    thinking = decomposition.pop("_thinking", "")
```
   （`error`/`done` 事件形状照现有 `:504-512` 逐字。）
3. `TaskManager(decomposition, edition=edition, use_loop=USE_AGENT_LOOP)`。
4. `TaskManager` 加 `use_loop`；引入 `_run_one(task_def)` 接缝：`use_loop` 真 → `_run_via_agentloop(task_def)`；否则 `TaskAgent().execute(task_def, edition=self.edition)`（**不变**）。把 `_execute_tier` 里硬编码的 `TaskAgent().execute` 改为 `self._run_one(task_def)`（仅此一处替换；其余 tier/并行/queue 不动）。
5. `_run_via_agentloop(task_def)` 镜像 `_run_single_task_loop`（chat 单任务版）但**多任务化**：发 `task_update(generating)` → `build_single_task_messages(..., predecessors=self._typed_predecessors(task_def))` → `AgentLoop(...)` → thinking→`task_thinking`、捕获 `_agent_outcome` → ASK_USER→`task_update(paused, result)`（**不发 done**，多任务的 done 由 orchestrator 统管）→ 否则 `task_update(validating)`→`run_validation`→`task_update(completed, result)`（**不发 content/done**）。`_typed_predecessors` 用 Task3 的 `task_result_from_legacy` 从 `_completed_results`+`_user_answers` 构造 `list[TaskResult]`（loop 模式**绕过** legacy `_inject_predecessor_context`）。
6. **resume 同接缝**：`resume_task`/`_resume_task` 在 `use_loop` 真时也走 `_run_one`/`_run_via_agentloop`，并把 resume 的 `summarize` 调用补上 `edition=`（修既有 bedrock 默认 bug）。

**SSE parity**：多任务事件（`task_list`/`task_update(generating|validating|completed|paused)`/`task_thinking`/`content`/`done`）逐字。对照 `TaskAgent.execute` 的 `task_update` data 键（`task_agent.py:947` 附近）确认 `_run_via_agentloop` 的 `generating` 形状一致。

- [ ] **Step 1: 写失败测试**

Create `tests/orchestrator/__init__.py`（空）、`tests/orchestrator/test_multitask_loop.py`（monkeypatch `build_default_registry`/`build_step`/`get_llm_client` 如 `test_orchestrator_loop.py`；用 `FakeStep` 脚本驱动）。至少：
- flag-on 两个独立任务都 completed，再 content(project)+done。
- flag-on 2 依赖 1：任务1 completed 先于任务2 generating；任务2 的 AgentLoop 收到的消息含任务1 命令（typed 注入端到端）——用记录消息的 FakeStep 断言。
- flag-on 任务1 ASK_USER：发 task_update(paused)，任务2 blocked，done，session 保活。
- 信号量：monkeypatch `MAX_PARALLEL_TASKS=1`，3 个 tier0 任务串行。

- [ ] **Step 2: 运行确认失败** → FAIL。

- [ ] **Step 3: 实现**（按「做法」；import Planner/to_legacy_decomposition/PlannerParseError/LLMError/TaskResult helpers/AgentLoop/build_*）。

- [ ] **Step 4: 运行确认通过 + flag-off 不变自查**

Run: `.venv/bin/python -m pytest tests/ -q` → 全绿。
Run: `git diff <T3_head>..HEAD -- backend/orchestrator/orchestrator.py` → 确认旧多任务执行逻辑除 `_run_one` 接缝替换 + 新方法 + Planner 分支外无改动。

- [ ] **Step 5: Commit**
```bash
git add backend/orchestrator/orchestrator.py tests/orchestrator/__init__.py tests/orchestrator/test_multitask_loop.py
git commit -m "feat(planner): orchestrator 多任务接线（use_loop 接缝 + Planner + 错误事件，flag-off 不变）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: summarize 路径核验

**Files:** Create `tests/orchestrator/test_summarize_path.py`（必要时小改 `orchestrator.py` 仅传 `edition=` 给 summarize）

**设计：** **保留 `MainAgent.summarize` 原样**（它消费 `get_completed_results()` 的 legacy list 形状，与执行器无关）。仅核验：loop 模式 `task_update(completed, result)` 的 `result` dict 含 `type`/`command`/`phases` 键，匹配 summarize 读取（`main_agent.py:482-495`）与 `_build_project_from_summary`。summarize 失败保留软降级（与 decompose 的硬失败不同——summarize 是事后，降级可接受）。

- [ ] **Step 1: 写测试**：① flag-on 2 completed → summarize 调用一次、入参 legacy 键齐、content(project) 发出；② flag-on 1 paused+1 completed → `all_completed()` 假 → done、**不**调 summarize、session 保活；③ summarize 抛 LLMError → 仍发 content（含降级 explanation），不崩流。

- [ ] **Step 2-3: 先红后绿**（多数应已绿；若 resume summarize 缺 edition 则补）。

- [ ] **Step 4: Commit**
```bash
git add tests/orchestrator/test_summarize_path.py backend/orchestrator/orchestrator.py
git commit -m "test(planner): summarize 路径核验（loop completed 形状 / 0-completed / 软降级）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: 回归门槛（flag-off 逐字 / flag-on happy / 修复 / 硬失败）

**Files:** Create `tests/orchestrator/test_phase3_regression.py`

- [ ] **Step 1: 写测试**：
1. **flag-off 多任务逐字**：`USE_AGENT_LOOP=False`，patch `MainAgent.decompose` 返回固定 2 任务、patch `TaskAgent.execute` 脚本事件；spy `Planner.plan` **0 调用**；断言完整事件序列 == golden（snapshot）。
2. **flag-on happy（单+多）**：patch `client.chat` 返回合法 decomposition JSON + patch `build_step`/`build_default_registry` 使每任务脚本 `finish(done,<single_command json>)`；断言 `task_list` ids 与 JSON 一致、执行、content(project)+done。
3. **flag-on 非法图修复**：`client.chat` 先环后净 → `client.chat` 调用 2 次、流仍出合法 task_list 并完成、无假单任务。
4. **flag-on 硬失败（UX 变更）**：`client.chat` 恒环 → `Planner.plan` 抛 `PlannerParseError` → orchestrator 发 `error` 事件（**非**假单任务）；断言有 `error` 事件且无单造任务 task_list。
5. **flag-on 传输失败**：`client.chat` 抛 `TransientLLMError` → 发 `error`，非假任务。

- [ ] **Step 2: 先红后绿 + 全量回归** → `.venv/bin/python -m pytest tests/ -q` 全绿（Phase1+2+3）。

- [ ] **Step 3: Commit**
```bash
git add tests/orchestrator/test_phase3_regression.py
git commit -m "test(planner): Phase 3 回归门槛 — flag-off 逐字 / flag-on happy / 修复 / 硬失败 error 事件

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage（设计 spec 第 5.4 Planner / 5.8 Orchestrator / 第 7 错误处理 / 决策⑥）**
- typed Decomposition/TaskDef + 图校验 → Task 1 ✓
- LLM + 有界修复 + 传输/解析区分 + 取消静默降级 → Task 2 ✓
- typed 前驱上下文（替换串拼）→ Task 3 ✓
- 多任务跑统一循环、保留分层并行、flag 后 → Task 4 ✓
- summarize 保留软降级 → Task 5 ✓
- 硬失败发 error 而非假任务（spec 第7「零静默降级」）→ Task 4/6 ✓

**2. Placeholder scan**：Task 3 golden 文案 + Task 4 测试骨架标注「实现者对照源文件取确切措辞/mock 点补全」——是明确验收门槛（parity 串、SSE 形状），非占位符。其余完整。

**3. Type/风险闭环**：
- `to_legacy_decomposition` 接缝保证 TaskManager/summarize 消费形状不变（不碰 models/schemas）✓
- prompt alias（task_id→id）让 model_validate 直吃 prompt JSON，prompt 冻结 ✓
- 传输 LLMError 不被 Planner 吞（Task2 两条传输测试）✓
- 预算：1+max_repairs，不叠加重试 ✓
- 前驱 parity golden（Task3）守串拼漂移 ✓
- flag-off 逐字（Task6 #1 golden + git diff）✓
- resume 走同接缝 + 补 edition（Task4 #6）✓
- 硬失败 UX 变更显式（Task6 #4，flag 后才生效，前端需渲染 error——记入风险）✓
