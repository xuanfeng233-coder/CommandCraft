# Phase 4 — Build 统一到 Planner + AgentLoop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 build 模式统一到 Planner + 统一 AgentLoop——build = `Planner.plan` → 渲染成 PROJECT.md 确认关卡（用户改/确认）→ 每步经 orchestrator 的 `TaskManager(use_loop=True)` 跑统一循环 → 确定性 regex 标记完成。藏在**独立**开关 `BUILD_USE_AGENT_LOOP`（默认关）后；flag-off 与今天的 build 路径（Clarify/Write/Reader/Review/Search 五件套）**逐字一致**。

**Architecture:** Phase 1-3 已交付 `backend/agentloop/`、`backend/agents/planner.py`（`Planner.plan→Decomposition`）、`planner_schemas.to_legacy_decomposition`，且 orchestrator 的 `TaskManager(use_loop=True)` 已经路由到 `_run_via_agentloop`。build flag-on 是一层薄适配：Planner → `decomposition_to_project_md`（**必须能被 `reader_agent.parse_plan` 回解** —— 这是承载契约）→ 确认 → 每步 `TaskManager(use_loop=True).execute_all()` → regex 标记。**不引入新执行引擎**。

**Tech Stack:** Python 3.11、asyncio、Pydantic；测试 pytest + pytest-asyncio。

## Global Constraints

- 语言：注释/docstring/面向用户字符串中文。
- **独立开关**：新增 `BUILD_USE_AGENT_LOOP`（默认 `false`），与 chat 的 `USE_AGENT_LOOP` 分离，build 可独立灰度。
- **flag-off 逐字一致**：`BUILD_USE_AGENT_LOOP=false` 时，build 的 clarify→search→write 规划 + 每步 decompose+TaskManager+ReviewAgent 重试 + write_agent 标记 路径**完全不变**。用 e2e snapshot + 不动 flag-off 分支体 自查。
- **本期删 0 文件**：`build/agents/*` 五个模块在 flag-off 仍 import 且行为不变，**不删**（Phase 5 才删 clarify/write.create_plan/review/search；`reader_agent` 永久保留）。
- **PROJECT.md 回解契约**：`decomposition_to_project_md` 输出必须经真实 `reader_agent.parse_plan` 回解出等量步骤（标题/顺序/状态一致）——round-trip 测试是合并门槛。标题禁含 `[` `]` `**`（会破 `_STEP_PATTERN`/`_FIELD_PATTERN`）。
- **Planner 无静默降级**：flag-on `start_build`/step 须 try/except `(PlannerParseError, Exception)` → 发 `error`+`done`，不让异常逃逸破坏 SSE 流。
- **测试目录**：仓库根 `tests/`（`pytest.ini testpaths=tests`）；新建 `tests/build/`、`tests/api/`（各含 `__init__.py`）。
- 提交频繁，提交信息中文，结尾附 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。测试 `.venv/bin/python -m pytest`，pristine。

---

## File Structure

**新建**
- `backend/build/plan_adapter.py` — `decomposition_to_project_md(d, user_request) -> str`
- `tests/build/__init__.py`、`tests/api/__init__.py`（空）
- `tests/build/test_plan_adapter.py` / `test_build_orchestrator_planner.py` / `test_build_step_loop.py` / `test_build_completeness.py` / `test_build_e2e_flag.py`
- `tests/api/test_build_api_flag.py`

**修改**
- `backend/config.py` — `BUILD_USE_AGENT_LOOP` / `BUILD_LOOP_REVIEW`
- `backend/build/build_orchestrator.py` — `__init__`(+planner) / `BuildState`(+edition,+planner_decomposition) / `start_build`(flag 分支 + `_plan_via_planner`) / `_execute_step`(flag 分支 + `_execute_step_loop` + 模块级 `_regex_mark_step_done`)
- `backend/api/build.py` — 把 `edition` 线程进 `start_build` → `BuildState.edition`；`/clarify` flag-on 防御性守卫（不删）

**删除：本期 0。**

---

## Task 1: Decomposition → PROJECT.md 适配器（回解门槛）

**Files:** Create `backend/build/plan_adapter.py`, `tests/build/__init__.py`, `tests/build/test_plan_adapter.py`

**Interface:** `decomposition_to_project_md(d: Decomposition, user_request: str) -> str`

**做法（关键）：** 先打开 `backend/build/agents/reader_agent.py` 读 `_STEP_PATTERN`/`_FIELD_PATTERN`/`parse_plan`/`get_overview`/`get_step` 的确切正则与字段名（`需求`/`实现思路`/`涉及命令` 等）。渲染每个 `TaskDef` 成能被 `parse_plan` 回解的块：
```
# {project_name}

{overview}

## 步骤 {i}: {sanitize(title)} [ ]
**需求**: {title or instruction}
**实现思路**: {sanitize(instruction)}
**涉及命令**: {", ".join(recommended_commands)}
- [ ] {sanitize(instruction)}
```
`sanitize` 去掉 `[` `]` `**` 与行尾空格。`depends_on` 写进正文（如 `**依赖**: 步骤 X`）。状态位**精确** `[ ]`（空格）。字段名以 reader_agent 源为准（若不是「需求/实现思路/涉及命令」，按源改）。

- [ ] **Step 1: 写回解测试**

Create `tests/build/__init__.py`（空）。Create `tests/build/test_plan_adapter.py`:
```python
from backend.agents.planner_schemas import Decomposition, TaskDef
from backend.build.agents import reader_agent
from backend.build.plan_adapter import decomposition_to_project_md


def _decomp(n=2, **kw):
    tasks = [TaskDef(id=str(i), title=f"步骤{i}标题", instruction=f"做第{i}件事",
                     recommended_commands=["/say hi"]) for i in range(1, n + 1)]
    return Decomposition(project_name="测试项目", overview="总览说明", tasks=tasks, **kw)


def test_roundtrip_step_count_and_order():
    d = _decomp(3)
    md = decomposition_to_project_md(d, "造个东西")
    steps = reader_agent.parse_plan(md)
    assert len(steps) == 3
    assert [s.title for s in steps] == [t.title for t in d.tasks]


def test_steps_pending_and_indexed():
    md = decomposition_to_project_md(_decomp(2), "x")
    steps = reader_agent.parse_plan(md)
    assert all(s.status == "pending" for s in steps)
    assert [s.index for s in steps] == [1, 2]


def test_overview_present_without_title_line():
    md = decomposition_to_project_md(_decomp(1), "x")
    ov = reader_agent.get_overview(md)
    assert "总览说明" in ov
    assert "测试项目" not in ov  # # title 行被 get_overview 截掉


def test_requirement_approach_nonempty():
    md = decomposition_to_project_md(_decomp(1), "x")
    step = reader_agent.get_step(md, 1)
    assert step is not None
    # 字段名以 reader_agent 源为准；断言能取到非空需求/思路
    raw = step.raw_content if hasattr(step, "raw_content") else str(step)
    assert "做第1件事" in raw


def test_title_with_brackets_and_stars_sanitized():
    d = Decomposition(project_name="P", overview="O",
                      tasks=[TaskDef(id="1", title="标题[含]**符号**", instruction="思路**粗**")])
    md = decomposition_to_project_md(d, "x")
    steps = reader_agent.parse_plan(md)
    assert len(steps) == 1  # 未被破坏


def test_empty_tasks_no_crash():
    md = decomposition_to_project_md(Decomposition(project_name="P", overview="O", tasks=[]), "x")
    assert reader_agent.parse_plan(md) == []


def test_empty_recommended_commands():
    d = Decomposition(project_name="P", overview="O",
                      tasks=[TaskDef(id="1", title="t", instruction="i", recommended_commands=[])])
    steps = reader_agent.parse_plan(decomposition_to_project_md(d, "x"))
    assert len(steps) == 1
```
> 实现者：先读 `reader_agent` 确认 `PlanStep` 字段名（`status` 值是 `"pending"` 还是别的、`title`/`index`/`raw_content` 属性名），把上面断言对齐真实属性；round-trip 计数与顺序是核心门槛。

- [ ] **Step 2: 运行确认失败** → FAIL。
- [ ] **Step 3: 实现** `backend/build/plan_adapter.py`。
- [ ] **Step 4: 运行确认通过** → PASS。
- [ ] **Step 5: Commit**
```bash
git add backend/build/plan_adapter.py tests/build/__init__.py tests/build/test_plan_adapter.py
git commit -m "feat(build): Decomposition→PROJECT.md 适配器（reader_agent 回解门槛）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: flag-on 规划路径（start_build 分支 + _plan_via_planner）

**Files:** Modify `backend/config.py`, `backend/build/build_orchestrator.py`；Create `tests/build/test_build_orchestrator_planner.py`

**Config:**
```python
BUILD_USE_AGENT_LOOP = os.environ.get("BUILD_USE_AGENT_LOOP", "false").lower() in ("1","true","yes")
```

**做法：** 先通读 `build_orchestrator.py`（`BuildState`、`start_build`、SSE `_sse` 辅助、`get_build_chat_client`、`project_manager` 用法、`continue_after_clarify`）。
- `BuildState` 加 `edition: str = "bedrock"` 与 `planner_decomposition: Decomposition | None = None`（**不删** clarify 字段）。
- `__init__` 加 `self.planner = Planner()`（import `backend.agents.planner.Planner`）。
- 新增 `_plan_via_planner(self, project_id, user_input, state)`：调 `self.planner.plan(user_input, session_context="", client=get_build_chat_client(), edition=state.edition)`（**try/except (PlannerParseError, Exception) → 发 error+done+return**）→ `md = decomposition_to_project_md(decomp, user_input)` → `state.plan_content=md`、`state.total_steps=len(reader_agent.parse_plan(md))` → `project_manager.update_status(...)` → 依次 yield `thinking` / `build_plan{markdown_content}` / `build_phase{phase:"reviewing"}` / `done`（事件形状对照现有 write 流）。
- `start_build`：在发完 `build_phase(planning)` 后插入 `if BUILD_USE_AGENT_LOOP: async for ev in self._plan_via_planner(...): yield ev; return`。**其余 clarify→search→write 分支体逐字不动**。flag-on **不发 `build_clarify`**。

- [ ] **Step 1: 写测试**（mock `Planner.plan` 返回固定 Decomposition；mock 五件套断言未被调）：
  1. flag-on 序列 `build_phase(planning)→thinking→build_plan→build_phase(reviewing)→done`，无 `build_clarify`。
  2. `clarify_agent.analyze`/`search_agent.search`/`write_agent.create_plan` 未被调。
  3. `state.total_steps == len(decomp.tasks)`；`build_plan.markdown_content` round-trips（`parse_plan` 计数相符）。
  4. flag-off：`clarify_agent.analyze` 被调（回归守卫）。
  5. Planner 抛 `PlannerParseError` → 发 `error`+`done`。

- [ ] **Step 2-4: 先红后绿 + 全量回归**（`.venv/bin/python -m pytest tests/ -q` 全绿；`git diff` 自查 flag-off 分支体未改）。
- [ ] **Step 5: Commit**
```bash
git add backend/config.py backend/build/build_orchestrator.py tests/build/test_build_orchestrator_planner.py
git commit -m "feat(build): BUILD_USE_AGENT_LOOP + start_build Planner 规划分支（flag-off 不变）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: flag-on 执行路径（_execute_step_loop + regex 标记）

**Files:** Modify `backend/build/build_orchestrator.py`；Create `tests/build/test_build_step_loop.py`

**做法：** `confirm_plan`/`_execute_all_steps` **不变**；只在 `_execute_step` 顶部加 `if BUILD_USE_AGENT_LOOP: async for ev in self._execute_step_loop(project_id, step_index): yield ev; return`。
新增 `_execute_step_loop`：
- 发 `build_step_update(reading)` → `project_manager.read_project_md` → `reader_agent.get_step(md, step_index)`（**保留 reader_agent**）。
- `step_request = self._build_step_request(step)`（复用）；`execution_context = self._build_execution_context(state, step_index)`（复用）。
- 发 `build_step_update(decomposing)` → `decomp,_ = await self.planner.plan(step_request, session_context=execution_context, client=get_build_chat_client(), edition=state.edition)`（try/except → failed）→ `legacy = to_legacy_decomposition(decomp, original_input=step_request)`；空 tasks → failed。
- 发 `task_list{...}` + `build_step_update(executing)` → `mgr = TaskManager(legacy, edition=state.edition); mgr.use_loop = True; async for ev in mgr.execute_all(): yield ev`（路由到 `_run_via_agentloop`）。
- `results = mgr.get_completed_results()`；`state.all_commands.extend(self._extract_all_commands(results))`、`state.accumulated_context = self._extract_step_artifacts(...)`（复用既有辅助）。
- 发 `build_step_update(updating)` → `updated = _regex_mark_step_done(md, step_index, summary, layout)` → `project_manager.write_project_md` → 发 `build_step_update(complete, ...)`。
- **`_regex_mark_step_done`**：把 `write_agent` 里的 `_regex_mark_done`（header `[ ]→[x]`、子任务 `- [ ]→- [x]`、插入 `**执行结果**`）提升为 `build_orchestrator.py` 模块级纯函数（无 LLM）；扩展可加 `**命令布局**` 块。flag-off 仍用 `write_agent.mark_step_done`。
- **flag-on 无 ReviewAgent 重试**（一步一次 TaskManager pass）。

- [ ] **Step 1: 写测试**（mock `Planner.plan` + stub `TaskManager`）：
  1. flag-on `_execute_step_loop` 状态序列 `reading→decomposing→executing→updating→complete`（无 reviewing/retrying）。
  2. `mgr.use_loop is True`（接缝生效）。
  3. `review_agent.review` 未调；`write_agent.mark_step_done` 未调。
  4. 标记后 `parse_plan(written)[idx-1].status == "done"`（regex 经 reader 回解）。
  5. 第 N 步的 `accumulated_context` 作为 `session_context` 注入第 N+1 步 `Planner.plan`（捕获 kwarg）。
  6. flag-off：`review_agent.review` + `write_agent.mark_step_done` 被调，重试循环在。

- [ ] **Step 2-4: 先红后绿 + 全量回归 + flag-off 自查**。
- [ ] **Step 5: Commit**
```bash
git add backend/build/build_orchestrator.py tests/build/test_build_step_loop.py
git commit -m "feat(build): _execute_step_loop（每步 Planner+TaskManager(use_loop) + regex 标记，flag-off 不变）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: 完整性复查（BUILD_LOOP_REVIEW 子开关，替代 ReviewAgent）

**Files:** Modify `backend/config.py`, `backend/build/build_orchestrator.py`；Create `tests/build/test_build_completeness.py`

**Config:** `BUILD_LOOP_REVIEW = os.environ.get("BUILD_LOOP_REVIEW","false").lower() in (...)`（仅 `BUILD_USE_AGENT_LOOP=true` 时有意义，默认关）。

**做法：** `BUILD_LOOP_REVIEW` 开时，`_execute_step_loop` 在 `mgr.execute_all()` 后跑一次额外 AgentLoop（registry 含 `validate_command`）对本步命令做完整性判定 `_loop_validate_step(step, results, edition)`：`ok/missing`；不 ok 且 `retry_count < BUILD_MAX_REVIEW_RETRIES` → 把 missing 附到重规划请求再跑一次（镜像旧重试上限）。完整性是循环 `finish` 的裁决，不另解析 JSON。**默认关** → Phase 4 先发「一步一 pass」。

- [ ] **Step 1: 写测试**：
  1. `BUILD_LOOP_REVIEW=False`（默认）：无 `reviewing` 事件、一次 TaskManager pass。
  2. `=True` + loop 判 complete：发 `reviewing`、无重试。
  3. `=True` + loop 判 missing：一次重试（missing 附加），上限 `BUILD_MAX_REVIEW_RETRIES`。
  4. 任何情况旧 `review_agent` 不被 import/调（flag-on）。

- [ ] **Step 2-4: 先红后绿 + 回归**。
- [ ] **Step 5: Commit**
```bash
git add backend/config.py backend/build/build_orchestrator.py tests/build/test_build_completeness.py
git commit -m "feat(build): BUILD_LOOP_REVIEW 完整性复查（loop/validate 替代 ReviewAgent，默认关）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: 接入 api/build.py（保契约 + edition 线程）

**Files:** Modify `backend/api/build.py`；Create `tests/api/__init__.py`, `tests/api/test_build_api_flag.py`

**做法（全部增量、不破契约）：**
1. `start_build`（`build.py` 约 :86）：把已读到的 `edition`（`X-MC-Edition`）线程进 `build_orchestrator.start_build(..., edition=edition)` 与 `BuildState.edition`（给 `start_build` 加 `edition` 形参）。
2. `clarify_build`（约 :157）：**保留**端点；flag-on 时前端不会调它（无 `build_clarify`）。防御：flag-on 且被调 → 返回一个无害 `done` SSE（不 404）。**不删**。
3. `confirm_build`/`update_plan`/`get_build_project`/list/delete：**不变**。
4. `_make_sse_stream`/contextvar 包裹：不变（flag-on 同样用 `get_build_chat_client()` contextvar）。

- [ ] **Step 1: 写测试**（FastAPI TestClient，最小 app 含 build router；monkeypatch orchestrator）：
  1. `POST /start` flag-on 返回含 `build_plan`+`done` 的 SSE；flag-off 含相同 + 可能 `build_clarify`；都 200。
  2. `POST /confirm` flag-on：`build_phase(executing)→task_list→build_step_update(...complete)→build_phase(completed){commands}→done`；`build_usage` 成功一次自增——与 flag-off 同。
  3. `/{id}/clarify` flag-off 仍可路由（仅 ownership 失败才 404）。
  4. 归属/限额 `_check_build_access` 两路不变。
  5. `X-MC-Edition` 到 `BuildState.edition` 再到 `Planner.plan(edition=...)`。

- [ ] **Step 2-4: 先红后绿 + 回归**。
- [ ] **Step 5: Commit**
```bash
git add backend/api/build.py tests/api/__init__.py tests/api/test_build_api_flag.py
git commit -m "feat(build): api/build edition 线程 + /clarify flag-on 防御（契约不变）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: E2E / 回归（flag-off 逐字 snapshot + flag-on happy）

**Files:** Create `tests/build/test_build_e2e_flag.py`

- [ ] **Step 1: 写测试**：
  1. **flag-off 逐字**：`BUILD_USE_AGENT_LOOP=False`，五件套 mock 成确定性输出，`start_build→confirm_plan` 端到端，捕获完整 SSE 列表做 snapshot；断言 `clarify_agent`/`search_agent`/`write_agent`/`review_agent` 均按记录顺序被调（回归锁）。
  2. **flag-on happy**：`=True`，mock `Planner.plan`（规划 + 每步）+ stub `TaskManager` 的 `_run_via_agentloop` 产 `completed`；全流 `start→build_plan→confirm→per-step→completed`；断言四个废弃 agent 均未调；`reader_agent`+`project_manager`+`to_legacy_decomposition`+`TaskManager(use_loop=True)` 被用。
  3. **round-trip 集成**：真实 `decomposition_to_project_md` → 真实 `reader_agent.parse_plan` → `_build_step_request` 每步非空。
  4. **confirm-after-restart**：丢 `_active_builds`，flag-on `confirm_plan` 仍从 PROJECT.md 重建执行。
  5. **edition 矩阵**：flag-on 跑 bedrock + java，断言 `Planner.plan(edition=...)` 收到对应 edition、选对 prompt 变体。

- [ ] **Step 2: 先红后绿 + 全量回归** → `.venv/bin/python -m pytest tests/ -q` 全绿（Phase1-4）。
- [ ] **Step 3: Commit**
```bash
git add tests/build/test_build_e2e_flag.py
git commit -m "test(build): Phase 4 e2e — flag-off 逐字 snapshot / flag-on happy / round-trip / restart / edition

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage（设计 spec 第 5.9 build=循环+确认门 / 决策①）**
- Planner 出计划 → 确认门（PROJECT.md）→ 同一 orchestrator 循环执行 → 完整性复查 → Tasks 1-4 ✓
- Clarify=ask_user / Write=Planner / Review=完整性 / Search=search_web 工具 —— 映射达成（删除 Phase 5）→ Tasks 2-4 ✓
- build 不再是第二套 agent 家族（flag-on）→ Tasks 2-3 ✓
- 保留确认 UX + project_manager 持久化 → Tasks 1/5 ✓
- 独立开关、flag-off 逐字 → 全局约束 + Task 6 snapshot ✓

**2. Placeholder scan**：Task 1/5 测试标注「字段名/属性以 reader_agent/build.py 源为准」——明确验收对齐，非占位符。round-trip 与 flag-off snapshot 是硬门槛。

**3. Type/风险闭环**：
- 回解契约（Task1 round-trip + 标题 sanitize）守 PROJECT.md 形状 ✓
- flag-off 逐字（Task6 snapshot + 不动分支体 + git diff）✓
- Planner 无静默降级 → flag-on try/except 发 error（Task2/3）✓
- 复用 orchestrator 接缝（`TaskManager.use_loop` / `_run_via_agentloop` / `to_legacy_decomposition`），不新引擎 ✓
- 删 0 文件，flag-off import 不破（Phase 5 才删）✓
- 完整性复查降级风险 → `BUILD_LOOP_REVIEW` 子开关（Task4，默认关，可不改码启用）✓
- restart 持久化 → confirm 从 PROJECT.md 重建（Task6 #4）✓
- 跨步 string accumulated_context vs 步内 typed predecessors 并存——记录为已知（Phase 4 接受）✓
