# 设计文档：CommandCraft 统一 Agent 循环重构

- **日期**：2026-06-21
- **状态**：设计已批准，待转实现计划
- **范围**：重构后端 Agent 工作逻辑，使其成为「严谨优雅、类 Claude Code」的统一工具循环；接入本地 SearXNG 联网搜索提升生成质量；顺带修复过时的 provider 模型列表（改为动态发现）。
- **不在本范围**：前端组件重写（仅在 SSE 事件契约变化处做最小适配）；多进程/重启可持久化的会话态（设计为可序列化，但本期不落地）。

---

## 1. 背景与现状

CommandCraft 是 Minecraft（基岩版 + Java 版）AI 命令生成平台。用户自然语言描述需求 → AI 生成合法命令。当前后端 Agent 逻辑存在以下结构性问题（基于 2026-06-21 全代码审计）：

1. **两套并行 Agent 栈**：chat 模式（`MainAgent.decompose` → `TaskManager` 分层并行 → `TaskAgent`）与 build 模式（`BuildOrchestrator` + `Clarify/Write/Read/Review` 四个单发 agent + 三阶段状态机）。执行引擎复用但外层重复，任何循环改进都要做两遍。
2. **不是真正的工具循环**：决策被前置进一个 1600+ 行的巨型 `decompose` prompt，执行是大多单发的扇出，校验是事后补丁。唯一的真工具循环 `TaskAgent._execute_with_tools`（≤5 轮）很浅：工具报错直接崩任务、预算耗尽静默、结果是无结构字符串、且对不支持工具的 provider 退化为无循环单发。
3. **校验不回喂模型**：`command_validator` 结果仅作为 warning 附加；`structural_validator` 虽会重试，但是外层 Python 重启一个新 `TaskAgent`（≤1 次），模型自己从不「观察」到校验失败再修复。
4. **JSON 全靠 regex 抽取，无 schema**：`BaseSkill.extract_json()`（3 套正则）是通用解析器。无 Pydantic 模型；非法 `depends_on`/重复 id/环只能被分层器弱兜底。
5. **失败静默降级**：decompose/summarize/review 广捕异常后返回「貌似合理」的降级结果（假单任务、空 phases、`complete=True`），超时与 JSON 损坏对调用方不可区分。
6. **字符串上下文管道**：前驱注入、build 的 `accumulated_context`、会话上下文都是不透明拼接串，无结构、无类型、build 重试循环里无界增长。
7. **RAG 子系统已死**：ChromaDB + bge-m3 四集合全建好但无人调用，且上次提交删了其依赖的 config 常量，import 即报错。
8. **SearXNG 完全不存在**：仅 build 模式有一个 2.4KB 的本地 wiki 搜索 `search_agent`（FTS5，固定 `is_authoritative=True`）。
9. **LLM 客户端无韧性**：`httpx` 调用无重试、无超时、无退避。
10. **模型列表写死且过时**：`backend/utils/providers.py` 的 `PROVIDERS` 是静态 dict，多处模型已过时或下线，需手动维护。

---

## 2. 目标与非目标

### 目标
- **G1 统一引擎**：chat 与 build 共用一个「计划 → 行动/调用工具 → 观察 → 校验 → 继续/终止」的循环，消除两套栈。
- **G2 真工具循环**：工具使用是脊柱；工具错误被观察并回喂；校验成为模型可调用、可据此自我修复的工具；终止是模型显式声明的一等动作。
- **G3 联网搜索提质**：接入本地 SearXNG，作为「本地知识优先、SearXNG 兜底」的搜索工具，best-effort（挂了降级不阻塞）。
- **G4 严谨**：Pydantic 契约贯穿；零静默降级；错误分类清晰；模块小而有界、可单测。
- **G5 动态模型发现**：运行时从 provider 拉取真实模型列表，curated 静态列表兜底，前端下拉始终最新。

### 非目标
- 不重写前端（仅适配 SSE 契约变化）。
- 不在本期实现多进程/重启可持久化会话态。
- 不复活向量 RAG（明确退休）。

---

## 3. 已锁定的设计决策

| # | 决策 | 选择 |
|---|---|---|
| ① | chat/build 引擎关系 | **统一为单一循环引擎**；build = 循环 + 计划确认关卡 |
| ② | SearXNG 接入形态与依赖 | **工具调用 + 本地优先兜底**；SearXNG 为 best-effort 软依赖 |
| ③ | 本地知识检索 | **词法 + 结构化查询工具为权威核心，退休向量 RAG**（删除 ChromaDB/bge-m3 依赖） |
| ④ | 主干契约 | **单一工具循环 + 提示式模拟兜底**（GLM 等无原生工具的 provider 走 prompted-JSON，藏在同一接口后） |
| ⑤ | 终止状态 / 澄清策略 | **一等显式终止动作 `done`/`ask_user`/`give_up`**；模型被指示「优先合理假设，仅真歧义时 ask_user」 |
| ⑥ | 总体方案 | **方案 A：规划器 + 并行任务循环**（保留大型项目并行扇出，但 Planner typed+校验+可修复，每任务跑统一循环） |
| ⑦ | 模型列表 | **动态发现**（运行时拉取 + curated 静态兜底，并更新现有列表） |

---

## 4. 架构总览

```
POST /api/chat ┐                              ┌─ 单任务快路 ─────────────┐
               ├─► Planner ─► Decomposition ──┤                          ├─► AgentLoop ─► LoopOutcome
/api/build/*  ─┘  (typed +    (校验/修复)     └─ 任务图 ─► Orchestrator ─┘     │
                   schema)                       (分层并行, 每任务一次循环)     │
                                                                              ▼
                          build: Decomposition ─► 计划确认关卡 ─► 用户确认 ─► 同一 Orchestrator

AgentLoop 每一步：
  LLMStep.next(messages, tools)        # native function-calling 或 prompted 模拟
    ├─ tool_calls → ToolRegistry.execute → Observation（错误被捕获回喂）→ 续循环
    └─ finish(done|ask_user|give_up)   → 终止

工具：lookup_command / lookup_ids / lookup_formatting / search_knowledge /
      search_web(SearXNG) / validate_command(校验即工具) / finish(终止动作)
```

---

## 5. 组件详细设计

### 5.1 `AgentLoop`（`backend/agent/loop.py`）

provider 无关的核心循环。职责单一：驱动「模型决策 → 执行工具 → 观察 → 续/终」。

**接口**
```python
async def run(
    self,
    messages: list[Message],
    tools: ToolRegistry,
    budget: LoopBudget,
    emit: EventSink,          # SSE 事件回调
) -> LoopOutcome: ...
```

**循环语义**
1. 调 `LLMStep.next(messages, tools)` 得 `StepResult`。
2. 若 `StepResult.tool_calls` 非空：逐个 `tools.execute(call)` → 得 `Observation`；把工具调用与 observation 追加进 `messages`；若 `budget.near_limit()` 追加一条预算告警（明确告知模型剩余步数）；continue。
3. 若 `StepResult.finish`：返回 `LoopOutcome(finish)`。
4. 若两者皆无（模型直接产文本）：视为隐式 `done`，但要求结构化结果（见 5.7 结果契约）；记录一次「未显式 finish」告警。
5. 步数达 `budget.max_steps`：强制收尾——再给模型一次「必须 finish」的最终调用；若仍不 finish，返回 `give_up` 并附诊断。

**不变量**
- 工具异常**永不**冒泡出循环：`ToolRegistry.execute` 内部捕获，转成 `Observation(ok=False, error=...)` 回喂。
- 终止只有三种显式态：`done` / `ask_user` / `give_up`。
- 循环对 native/prompted 无感（全藏在 `LLMStep` 后）。

### 5.2 `LLMStep`（`backend/agent/step.py`）

统一「模型走一步并可能请求工具」的抽象，屏蔽 provider 差异。

- `NativeToolStep`：用 provider 原生 function-calling（`tools=` 参数）。
- `PromptedToolStep`：对不支持原生工具的 provider（如 GLM），把工具 schema 注入 system prompt，约定模型输出 `{"tool_calls":[...]}` 或 `{"finish":{...}}` 的 JSON 协议，解析为同一 `StepResult`。解析失败 → 回喂「协议错误」让模型重试（有界）。
- 选择策略：依据 `ProviderInfo.supports_tools`（curated 能力元数据）。
- provider 怪癖（DeepSeek `reasoning_content` 等）隔离在 adapter，不进循环。

### 5.3 `ToolRegistry` 与工具（`backend/agent/tools/`）

chat 与 build 共享同一注册表。`execute(call) -> Observation` 统一捕获异常、做 token 预算截断、可选结果排序。

| 工具 | 文件 | 说明 |
|---|---|---|
| `lookup_command(name)` | `tools/lookup.py` | 命令用法文档（结构化，来自 KnowledgeLoader，按 edition） |
| `lookup_ids(category, query)` | `tools/lookup.py` | ID 注册表检索（items/blocks/entities/…，IDRegistry） |
| `lookup_formatting()` | `tools/lookup.py` | 格式化代码 |
| `search_knowledge(query)` | `tools/search.py` | 本地 wiki FTS5 + 结构化 KB（词法），权威核心 |
| `search_web(query)` | `tools/search.py` | SearXNG，best-effort（见 5.5） |
| `validate_command(cmd)` | `tools/validate.py` | **校验即工具**：跑 command/structural validator，返回结构化 `ValidationReport` 作为 observation |
| `finish(status, payload)` | `tools/finish.py` | 终止动作 `done`/`ask_user`/`give_up` |

**校验即工具（核心改变）**：`validate_command` 把现有 `skills/command_validator.py` + `skills/structural_validator.py` 包成一个工具，返回结构化 errors/warnings。模型可在生成后主动调用、读到结构化错误、自我修复，循环内闭环——取代当前「事后 warning + 外层重启子 agent」。

### 5.4 `Planner`（`backend/agent/planner.py`）

- 输入：用户请求 + **typed 会话上下文**（`list[Message]`，非拼接串）+ edition。
- 输出：`Decomposition`（Pydantic）：
  ```python
  class TaskDef(BaseModel):
      id: str
      title: str
      instruction: str
      depends_on: list[str] = []
  class Decomposition(BaseModel):
      project_name: str
      overview: str
      is_single_task: bool
      tasks: list[TaskDef]
  ```
- **立即校验**：id 唯一；`depends_on` 全部指向存在 id；无环（拓扑可排）。
- **非法 → 修复**：把 schema/图错误回喂模型重提示，有界 `PLANNER_MAX_REPAIR=2`。
- **传输失败 → 显式报错**：区分「传输失败」与「模型产出非法」，二者都上报，**绝不**静默降级成假单任务。
- 单任务快路：`is_single_task=True` 跳过图机制，直接交 `AgentLoop`。

### 5.5 `SearchService` 与 SearXNG（`backend/agent/tools/search.py`）

```python
async def search(self, query: str) -> SearchResult:
    hits = await self.local.search(query)          # wiki FTS5 + 结构化 KB
    if hits.sufficient():                          # 命中阈值
        return hits
    try:
        web = await self.searxng.search(query)     # 兜底上网
        return merge(hits, web)
    except SearxngUnavailable:
        return hits.or_degraded_note()             # best-effort：挂了不阻塞
```

- **SearXNG 客户端**：async httpx，超时 + 重试；解析 JSON 结果；结果去重/排序；citation 跟踪；**token 预算截断**；TTL 缓存（默认 30 min）。这些当前全无，net-new。
- **软依赖**：启动/运行时健康检查；不可用时 `search_web` 返回「网络搜索暂不可用」observation，循环用本地知识照常完成。
- **部署**：SearXNG 作为独立 PM2 进程（loopback），nginx 不直接暴露；后端经 `SEARXNG_BASE_URL`（默认 `http://127.0.0.1:8888`）访问。运维细节写进 CLAUDE.md 部署段。

### 5.6 LLM 管线（`backend/llm/`）

**`client.py`（韧性客户端）**
- 指数退避重试、超时、瞬时/永久错误分类（网络/5xx/429 可重试；4xx 鉴权/参数不可重试）。
- provider 怪癖隔离在 adapter（DeepSeek `reasoning_content`、GLM 无 tools 等）。
- contextvars 覆盖（订阅用户）机制保留。

**`catalog.py`（`ModelCatalog` 动态模型发现）**
- 运行时 `GET {base_url}/models`（OpenAI 兼容），TTL 缓存（默认 6h）。
- 拉不到/不支持/超时 → 回落 curated 静态列表（且本次重构同步把 `providers.py` 现有列表更新到最新）。
- Gemini 用其 OpenAI 兼容 `/v1beta/openai/models`；Doubao（需 endpoint_id）/custom 仍可手填。
- 能力标志（`supports_tools`/`supports_thinking`）保留为 curated 元数据（models 接口通常不返回能力），只动态刷新 model id 列表。
- 经 `/api/settings`（或 `/api/settings/models`）暴露给前端。

**`providers.py`**：保留 `ProviderInfo`，但 `models` 字段语义变为「curated 兜底列表」；运行时优先用 `ModelCatalog` 的动态结果。

### 5.7 数据契约（`backend/agent/schemas.py`）

Pydantic 贯穿，上下文为 typed 对象：

- `Message`（role + content + 可选 tool_call/tool_result）
- `Decomposition` / `TaskDef`
- `TaskResult`（id, status, commands, validation: ValidationReport, explanation）
- `ToolCall` / `Observation`（ok, content, error?）
- `ValidationReport`（errors[], warnings[], structural[]）
- `StepResult`（tool_calls? | finish? | text?）
- `FinishAction`（status: done|ask_user|give_up, payload）
- `LoopOutcome`（finish, transcript, usage）
- `LoopBudget`（max_steps, validate_repair_max, planner_repair_max）
- `ModelInfo`（id, provider, …）

### 5.8 Orchestrator（`backend/agent/orchestrator.py`，瘦身）

- 拓扑分层；层内并行（`asyncio.Semaphore(MAX_PARALLEL_TASKS)`）。
- 每任务 = 一次 `AgentLoop.run`，输入任务 instruction + **typed 前驱 `TaskResult`**（不再字符串拼接）。
- SSE 事件：`task_start` / `tool_call` / `task_result` / `error` / `content`。
- 失败为 typed failure，传播给依赖方（可选继续/失败），不静默丢弃。
- summarize（多任务）保留为一次循环或一次结构化 LLM 调用，产出 `{explanation, phases[]}`；`_post_process_project`（命令方块布局 + 终校验）保留。

### 5.9 Build 模式 = 循环 + 确认关卡（`backend/build/`，瘦身）

- 删除 `build/agents/{clarify,write,reader,review}_agent.py` 与 `search_agent.py`。
- **Clarify** = 循环 `ask_user` 终止态；**Write** = Planner；**确认** = 渲染 `Decomposition` 为 PROJECT.md / 确认关卡；**执行** = 同一 Orchestrator；**Review** = 一次以「完整性检查」为目标的循环运行（或并入 per-task `validate`）。
- `BuildOrchestrator` 退化为「Planner → 确认门 → Orchestrator」的薄编排 + 状态机（plan/confirm/execute）。
- 跨步上下文用 typed `TaskResult` 累积，不再 `accumulated_context` 串。

---

## 6. 模块结构（拆 monolith）

```
backend/agent/
  loop.py          # AgentLoop 核心循环
  step.py          # LLMStep: NativeToolStep + PromptedToolStep
  planner.py       # Planner + Decomposition 校验/修复
  orchestrator.py  # 分层并行（瘦身）
  schemas.py       # Pydantic 契约
  tools/
    registry.py    # ToolRegistry
    lookup.py      # lookup_command / lookup_ids / lookup_formatting
    search.py      # SearchService(LocalKnowledge + SearXNG)
    validate.py    # validate_command（校验即工具）
    finish.py      # finish 终止动作
  prompts/         # 抽出的模板（Bedrock/Java 共享 schema + 版本 delta）
backend/llm/
  client.py        # 韧性客户端
  catalog.py       # ModelCatalog 动态发现
  providers.py     # ProviderInfo + 怪癖隔离（curated 兜底）
```

- `skills/`（command_validator / structural_validator / template_builder / command_block_layout / output_formatter）**保留**，作为工具/工具函被循环调用。
- 被替换/删除：`agents/main_agent.py`、`agents/task_agent.py`、旧 `orchestrator/orchestrator.py`、`build/agents/*`、死的 `rag/*`。
- 4 个巨型 prompt 抽成 `prompts/` 模板，Bedrock/Java 共享 schema + 版本 delta（消除两份近重复）。

---

## 7. 错误处理（零静默降级）

三类错误，分别处理、都记录上报：
1. **传输类**（网络/5xx/429/超时）→ 退避重试；超过上限显式失败。
2. **解析/schema 类**（模型产出非法 JSON / 违反 schema / 非法任务图）→ 回喂错误让模型重试，有界（`PLANNER_MAX_REPAIR`、prompted 协议重试上限）。
3. **领域/校验类**（命令非法）→ 作为 observation 回喂，模型在循环内修复，有界 `validate_repair_max`。

传输失败 ≠ JSON 损坏：调用方可区分；不再返回「貌似合理」的假结果。

---

## 8. 测试策略

- **纯单测（无 LLM）**：
  - Planner schema 校验（喂罐装输出，断言唯一 id/无环/非法触发修复）。
  - `ToolRegistry.execute` 错误恢复（工具抛异常 → `Observation(ok=False)`）。
  - `SearchService` policy（假 LocalKnowledge + 假 SearXNG，断言本地优先、SearXNG 挂掉降级）。
  - `ModelCatalog`（假 `/v1/models` 响应 + 失败回落 curated）。
  - `PromptedToolStep` JSON 协议解析（含解析失败重试）。
- **Mock `LLMStep`**：用确定性「工具调用脚本」驱动 `AgentLoop`，断言错误恢复、预算告警、强制收尾、三种终止态。
- **集成**：几条录制 LLM 响应的端到端循环（chat 单任务、chat 多任务图、build 三阶段）。

---

## 9. 迁移分期（增量，每期可独立上线）

1. **地基**（低风险，立即见效）：`schemas.py` Pydantic 契约 + `llm/client.py` 韧性 + `llm/catalog.py` 动态模型发现（直接解决模型列表过时痛点）。
2. **循环**：`AgentLoop` + `ToolRegistry` + 校验即工具 + `search_web`；先接 chat 单任务路径。
3. **图**：typed `Planner` + 瘦身 `Orchestrator`；接 chat 多任务。
4. **统一 build**：确认关卡套在循环上，删旧 build agent 家族。
5. **清理**：删死 `rag/`、删降级路径重复、抽 `prompts/` 模板、更新 CLAUDE.md（部署段加 SearXNG）。

---

## 10. 可调参数默认值（已批准）

- **迭代预算**：循环 `max_steps≈8`；校验修复 `validate_repair_max=3`；Planner 修复 `planner_repair_max=2`。
- **持久化**：本期沿用内存会话态（**不做**多进程持久化），但 `LoopOutcome`/会话态设计为**可序列化对象**，以后加持久化不需重写。
- **延迟/成本**：无硬指标；以「有界预算 + TTL 缓存 + 本地优先搜索」控制 LLM 往返。
- **SearXNG**：软依赖，`SEARXNG_BASE_URL` 默认 `http://127.0.0.1:8888`，健康检查失败仅降级不阻塞。

---

## 11. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 工具循环增加 LLM 往返 → 延迟/成本上升 | 有界预算；本地优先搜索；TTL 缓存；单任务快路跳过图 |
| prompted 工具模拟（GLM）脆弱 | 协议解析失败回喂重试（有界）；DeepSeek 等原生工具为一等公民 |
| SearXNG 自托管运维负担 | 软依赖，挂了降级；独立 PM2 进程；写进部署文档 |
| `/v1/models` 各家差异 | curated 静态兜底；Gemini 用兼容端点；Doubao/custom 手填 |
| 大重构回归风险 | 分 5 期增量上线；每期可独立验证；旧栈逐步替换而非一次性 |

---

## 12. 待实现计划细化的开放点

- `prompts/` 模板引擎选型（Jinja2 vs 结构化 prompt-builder）——倾向 prompt 为数据、可不重启编辑。
- summarize 用「一次循环」还是「一次结构化 LLM 调用」——实现期定。
- SSE 事件契约的精确字段（前端适配点）——实现期与前端 store 对齐。
