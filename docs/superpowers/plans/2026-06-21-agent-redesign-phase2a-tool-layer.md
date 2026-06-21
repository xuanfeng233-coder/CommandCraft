# Phase 2A — 统一循环工具层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立统一 Agent 循环的「工具层」——Pydantic/dataclass 契约 + ToolRegistry + 7 个工具（4 个 edition 感知的本地查询 + 校验即工具 + SearXNG 联网搜索 + finish 终止动作），全部独立可测，不触碰 orchestrator/chat 运行路径。

**Architecture:** 新建 `backend/agentloop/` 包（**刻意用单数 `agentloop` 而非 `agent`，避开与既有 `backend/agents/` 复数包的混淆**）。本期只交付工具层与数据契约；AgentLoop 循环体、LLMStep、orchestrator 接线在 Phase 2B。工具复用 Phase 1 的 `backend/llm/url_guard.py`，并把既有 `backend/tools/command_tools.py` 的 4 个工具 schema 原样搬入、但修复其 edition 感知（当前用 bedrock-only 单例）。

**Tech Stack:** Python 3.11、Pydantic v2、dataclasses、httpx（async）；测试 pytest + pytest-asyncio + respx（Phase 1 已装）。

## Global Constraints

- 语言：注释/docstring/面向用户字符串为中文。
- 异步优先：所有 IO（搜索、HTTP）用 async。
- **工具线级名称不变**：4 个既有工具的 OpenAI schema `name` 保持 `get_command_usage` / `get_parameter_options` / `get_formatting_codes` / `search_wiki`（LLM 契约不变）。Python handler 函数名可用 `handle_*`。
- **零静默降级**：`search_web` 任何失败（url_guard 拒绝/超时/连接/非 200/JSON 错）都返回 `Observation(ok=..., data={"hits":[]})` 并 `logger.warning`，**绝不向循环抛异常**。
- **tool message 的 `content` 必须是 str**：所有 `Observation` 经 `to_tool_content()` 序列化为字符串（OpenAI API 要求，见 `backend/utils/llm_client.py` `_prep_messages`）。
- **不改运行路径**：本期不 import 进 orchestrator/chat/task_agent，不改其行为。仅新增模块 + 给 `url_guard` 加一个**向后兼容**的可选参数 + 给 `config.py` 加新配置项。
- **复用 Phase 1**：SearXNG URL 校验复用 `backend.llm.url_guard.assert_safe_outbound_url`（本期为它加 `allow_loopback` 参数）；不重新实现 SSRF 逻辑。
- 提交频繁：每个 Task 末尾 commit；提交信息中文，结尾附
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- 测试从仓库根 `.venv/bin/python -m pytest` 运行，输出须 pristine（无 warning）。

---

## File Structure

**新建**
- `backend/agentloop/__init__.py`（空）
- `backend/agentloop/schemas.py` — `Observation` / `ToolCall` / `StepResult` / `LoopBudget` / `FinishReason` / `AgentOutcome` / `ValidationIssue` / `ValidationReport`
- `backend/agentloop/tools/__init__.py`（空）
- `backend/agentloop/tools/registry.py` — `ToolContext` / `RegisteredTool` / `ToolRegistry`
- `backend/agentloop/tools/lookup.py` — 4 个 edition 感知本地查询 handler + `register_lookup_tools`
- `backend/agentloop/tools/validate.py` — `validate_command` schema + handler + `make_validation_report` + `register_validate_tool`
- `backend/agentloop/searxng_client.py` — `WebHit` / `SearXNGClient` / `get_searxng_client`
- `backend/agentloop/tools/search.py` — `search_web` handler + `register_search_tools`
- `backend/agentloop/tools/finish.py` — `finish` schema + handler + `register_finish_tool`；以及 `build_default_registry`（装配 7 个工具）

**修改**
- `backend/llm/url_guard.py` — 给 `assert_safe_outbound_url` 加 `allow_loopback: bool = False`（向后兼容）
- `backend/config.py` — 新增 `SEARXNG_URL` / `SEARXNG_TIMEOUT` / `WEB_SEARCH_MAX_RESULTS`

**新建测试**
- `tests/agentloop/__init__.py`（空）
- `tests/agentloop/test_schemas.py` / `test_registry.py` / `test_lookup.py` / `test_validate.py` / `test_searxng_client.py` / `test_search.py` / `test_finish_and_registry.py`
- `tests/llm/test_url_guard.py` — 追加 `allow_loopback` 用例（既有文件）

---

## Task 1: 数据契约 schemas.py

**Files:**
- Create: `backend/agentloop/__init__.py`（空）
- Create: `backend/agentloop/schemas.py`
- Test: `tests/agentloop/__init__.py`（空）、`tests/agentloop/test_schemas.py`

**Interfaces:**
- Consumes: 无。
- Produces:
  - `@dataclass Observation(tool_name:str, ok:bool, summary:str, data:dict=…, error:str|None=None)` + `to_tool_content() -> str`
  - `@dataclass ToolCall(id:str, name:str, arguments:dict)`
  - `@dataclass StepResult(content:str, thinking:str, tool_calls:list[ToolCall], raw_assistant_msg:dict)`
  - `@dataclass LoopBudget(max_rounds:int=8, warn_at_round:int=7, max_tool_calls:int=12, max_search_web_calls:int=2)` + `warning_text(rounds_used:int)->str`
  - `class FinishReason(str, Enum)`: `DONE/ASK_USER/GIVE_UP/IMPLICIT_DONE/BUDGET_EXHAUSTED`
  - `@dataclass AgentOutcome(reason:FinishReason, content:str, thinking:str, observations:list[Observation], rounds_used:int, error:str|None=None)`
  - `class ValidationIssue(BaseModel)`: `command,type,message,suggestion="",severity:Literal["error","warning"]`
  - `class ValidationReport(BaseModel)`: `valid:bool, error_count:int, warning_count:int, issues:list[ValidationIssue], feedback_text:str`

- [ ] **Step 1: 写失败测试**

Create `tests/agentloop/__init__.py`（空文件）。
Create `tests/agentloop/test_schemas.py`:
```python
import json

from backend.agentloop.schemas import (
    AgentOutcome,
    FinishReason,
    LoopBudget,
    Observation,
    StepResult,
    ToolCall,
    ValidationIssue,
    ValidationReport,
)


def test_observation_to_tool_content_is_str_summary_only():
    obs = Observation(tool_name="x", ok=True, summary="结果文本")
    content = obs.to_tool_content()
    assert isinstance(content, str)
    assert "结果文本" in content


def test_observation_to_tool_content_includes_data_json():
    obs = Observation(tool_name="x", ok=True, summary="摘要", data={"k": 1})
    content = obs.to_tool_content()
    assert isinstance(content, str)
    assert "摘要" in content
    # data 以 JSON 形式附带，模型可解析
    assert '"k"' in content and "1" in content


def test_observation_error_serializes():
    obs = Observation(tool_name="x", ok=False, summary="失败", error="boom")
    content = obs.to_tool_content()
    assert isinstance(content, str)
    assert "boom" in content


def test_loop_budget_defaults_and_warning():
    b = LoopBudget()
    assert b.max_rounds == 8
    assert b.warn_at_round == 7
    assert b.max_search_web_calls == 2
    w = b.warning_text(7)
    assert isinstance(w, str) and ("7" in w or "finish" in w)


def test_finish_reason_is_str_enum():
    assert FinishReason.DONE == "done"
    assert FinishReason("ask_user") is FinishReason.ASK_USER


def test_step_result_and_toolcall():
    sr = StepResult(content="hi", thinking="", tool_calls=[ToolCall("id1", "finish", {"reason": "done"})], raw_assistant_msg={"role": "assistant", "content": "hi"})
    assert sr.tool_calls[0].name == "finish"
    assert sr.raw_assistant_msg["role"] == "assistant"


def test_agent_outcome_holds_trace():
    out = AgentOutcome(reason=FinishReason.DONE, content="c", thinking="t", observations=[], rounds_used=2)
    assert out.reason is FinishReason.DONE
    assert out.rounds_used == 2


def test_validation_report_roundtrip():
    rep = ValidationReport(
        valid=False, error_count=1, warning_count=0,
        issues=[ValidationIssue(command="/give @p x", type="id", message="未知物品", severity="error")],
        feedback_text="❌ 1 个错误",
    )
    dumped = rep.model_dump()
    assert dumped["valid"] is False
    assert dumped["issues"][0]["severity"] == "error"
    # 可被 json 序列化（进 Observation.data）
    json.dumps(dumped, ensure_ascii=False)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/agentloop/test_schemas.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'backend.agentloop'`）。

- [ ] **Step 3: 实现**

Create `backend/agentloop/__init__.py`（空文件）。
Create `backend/agentloop/schemas.py`:
```python
"""统一 Agent 循环的数据契约（dataclass + Pydantic）。

Observation 是每个工具 handler 的返回；StepResult 是 LLMStep 每轮产出；
AgentOutcome 是循环终止结果；ValidationReport 是 validate_command 工具的结构化报告。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel


@dataclass
class Observation:
    """工具执行的结构化结果。ok=False 表示降级/出错，但仍回喂给模型自我纠正。"""

    tool_name: str
    ok: bool
    summary: str  # 面向 LLM 的文本，进入 {"role":"tool","content": ...}
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_tool_content(self) -> str:
        """序列化为 tool message 的 content 字符串（必须是 str）。"""
        parts = [self.summary] if self.summary else []
        if self.error:
            parts.append(f"[错误] {self.error}")
        if self.data:
            parts.append(
                "[数据] " + json.dumps(self.data, ensure_ascii=False)
            )
        return "\n".join(parts) if parts else "(无内容)"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class StepResult:
    content: str
    thinking: str
    tool_calls: list[ToolCall]
    raw_assistant_msg: dict[str, Any]


@dataclass
class LoopBudget:
    """循环预算。max_rounds 含 validate/finish 往返，故默认比旧的 5 高。"""

    max_rounds: int = 8
    warn_at_round: int = 7
    max_tool_calls: int = 12
    max_search_web_calls: int = 2

    def warning_text(self, rounds_used: int) -> str:
        return (
            f"已用 {rounds_used}/{self.max_rounds} 轮，请尽快调用 finish 给出最终答案。"
        )


class FinishReason(str, Enum):
    DONE = "done"
    ASK_USER = "ask_user"
    GIVE_UP = "give_up"
    IMPLICIT_DONE = "implicit_done"
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass
class AgentOutcome:
    reason: FinishReason
    content: str
    thinking: str
    observations: list[Observation]
    rounds_used: int
    error: str | None = None


class ValidationIssue(BaseModel):
    command: str
    type: str
    message: str
    suggestion: str = ""
    severity: Literal["error", "warning"]


class ValidationReport(BaseModel):
    valid: bool
    error_count: int
    warning_count: int
    issues: list[ValidationIssue]
    feedback_text: str
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/agentloop/test_schemas.py -v`
Expected: PASS（8 passed）。

- [ ] **Step 5: Commit**

```bash
git add backend/agentloop/__init__.py backend/agentloop/schemas.py tests/agentloop/__init__.py tests/agentloop/test_schemas.py
git commit -m "feat(agentloop): 数据契约 schemas（Observation/StepResult/LoopBudget/ValidationReport 等）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: ToolRegistry 与 ToolContext

**Files:**
- Create: `backend/agentloop/tools/__init__.py`（空）
- Create: `backend/agentloop/tools/registry.py`
- Test: `tests/agentloop/test_registry.py`

**Interfaces:**
- Consumes: `backend.agentloop.schemas.Observation`、`LoopBudget`。
- Produces:
  - `@dataclass ToolContext(edition:str, budget:LoopBudget, counters:dict[str,int])`
  - `@dataclass RegisteredTool(schema:dict, handler:ToolHandler)`
  - `ToolHandler = Callable[[dict, ToolContext], Awaitable[Observation]]`
  - `class ToolRegistry`: `register(schema, handler)`、`get_schemas()->list[dict]`、`names()->set[str]`、`async execute(name, args, ctx)->Observation`（未知工具→`Observation(ok=False, error="未知工具: <name>")`；handler 抛异常→`Observation(ok=False, error=str(e))`，**不外抛**）

- [ ] **Step 1: 写失败测试**

Create `backend/agentloop/tools/__init__.py`（空文件）。
Create `tests/agentloop/test_registry.py`:
```python
import pytest

from backend.agentloop.schemas import LoopBudget, Observation
from backend.agentloop.tools.registry import ToolContext, ToolRegistry


def _ctx():
    return ToolContext(edition="bedrock", budget=LoopBudget(), counters={})


def _schema(name):
    return {"type": "function", "function": {"name": name, "description": "d", "parameters": {"type": "object", "properties": {}}}}


async def test_register_and_execute():
    reg = ToolRegistry()

    async def handler(args, ctx):
        return Observation(tool_name="t", ok=True, summary=f"got {args.get('x')}")

    reg.register(_schema("t"), handler)
    assert reg.names() == {"t"}
    assert reg.get_schemas() == [_schema("t")]
    obs = await reg.execute("t", {"x": 5}, _ctx())
    assert obs.ok and "got 5" in obs.summary


async def test_unknown_tool_returns_error_observation():
    reg = ToolRegistry()
    obs = await reg.execute("nope", {}, _ctx())
    assert obs.ok is False
    assert "未知工具" in (obs.error or "")


async def test_handler_exception_becomes_observation():
    reg = ToolRegistry()

    async def boom(args, ctx):
        raise RuntimeError("explode")

    reg.register(_schema("b"), boom)
    obs = await reg.execute("b", {}, _ctx())
    assert obs.ok is False
    assert "explode" in (obs.error or "")
    assert obs.tool_name == "b"
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/agentloop/test_registry.py -v`
Expected: FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 实现**

Create `backend/agentloop/tools/registry.py`:
```python
"""工具注册表：统一注册/分发工具，并把 handler 异常转成 Observation（绝不外抛）。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from backend.agentloop.schemas import LoopBudget, Observation

logger = logging.getLogger(__name__)

ToolHandler = Callable[[dict[str, Any], "ToolContext"], Awaitable[Observation]]


@dataclass
class ToolContext:
    edition: str
    budget: LoopBudget
    counters: dict[str, int]


@dataclass
class RegisteredTool:
    schema: dict[str, Any]
    handler: ToolHandler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, schema: dict[str, Any], handler: ToolHandler) -> None:
        name = schema["function"]["name"]
        self._tools[name] = RegisteredTool(schema=schema, handler=handler)

    def get_schemas(self) -> list[dict[str, Any]]:
        return [t.schema for t in self._tools.values()]

    def names(self) -> set[str]:
        return set(self._tools.keys())

    async def execute(
        self, name: str, args: dict[str, Any], ctx: "ToolContext"
    ) -> Observation:
        tool = self._tools.get(name)
        if tool is None:
            return Observation(tool_name=name, ok=False, summary="", error=f"未知工具: {name}")
        try:
            return await tool.handler(args, ctx)
        except Exception as exc:  # noqa: BLE001 - 工具错误转 Observation，循环不崩
            logger.warning("工具 %s 执行异常：%s", name, exc)
            return Observation(
                tool_name=name, ok=False,
                summary=f"工具 {name} 执行失败",
                error=str(exc),
            )
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/agentloop/test_registry.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: Commit**

```bash
git add backend/agentloop/tools/__init__.py backend/agentloop/tools/registry.py tests/agentloop/test_registry.py
git commit -m "feat(agentloop): ToolRegistry + ToolContext（handler 异常转 Observation）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: edition 感知的本地查询工具 lookup.py

**Files:**
- Create: `backend/agentloop/tools/lookup.py`
- Test: `tests/agentloop/test_lookup.py`

**Interfaces:**
- Consumes: `backend.tools.command_tools.TOOL_DEFINITIONS`（4 个 schema 原样复用）；`backend.knowledge.loader.get_loader`；`backend.knowledge.wiki_search.wiki_searcher`；`ToolRegistry`/`ToolContext`/`Observation`。
- Produces: 4 个 handler（`handle_get_command_usage` / `handle_get_parameter_options` / `handle_get_formatting_codes` / `handle_search_wiki`）+ `register_lookup_tools(reg)`。**全部经 `get_loader(ctx.edition)` 取数据**（修复既有 bedrock-only 单例问题）。

**背景（关键）：** `backend/tools/command_tools.py` 的 `_get_command_usage` / `_get_parameter_options` / `_get_formatting_codes` 用模块级 `knowledge_loader`（bedrock 专用），**忽略 edition**。本任务把它们的逻辑搬到 edition 感知版本——用 `get_loader(ctx.edition)` 替换 `knowledge_loader`。其余格式化逻辑（搜索过滤、MAX_ENTRIES=50、行格式）逐字保留。`build_command_directory_text(edition)`（同文件 :228）已是 `get_loader(edition)` 的正确范例，照抄其 loader 用法。

- [ ] **Step 1: 写失败测试**

Create `tests/agentloop/test_lookup.py`:
```python
import pytest

from backend.agentloop.schemas import LoopBudget, Observation
from backend.agentloop.tools.lookup import register_lookup_tools
from backend.agentloop.tools.registry import ToolContext, ToolRegistry


def _ctx(edition="bedrock"):
    return ToolContext(edition=edition, budget=LoopBudget(), counters={})


def _reg():
    reg = ToolRegistry()
    register_lookup_tools(reg)
    return reg


def test_registers_four_wire_names():
    reg = _reg()
    assert {"get_command_usage", "get_parameter_options", "get_formatting_codes", "search_wiki"} <= reg.names()


async def test_get_command_usage_known_command_bedrock():
    obs = await _reg().execute("get_command_usage", {"command_name": "give"}, _ctx("bedrock"))
    assert isinstance(obs.to_tool_content(), str)
    # give 是基岩版核心命令，应能查到（summary 含命令名）
    assert obs.ok is True
    assert "give" in obs.summary.lower()


async def test_get_command_usage_unknown_is_not_ok():
    obs = await _reg().execute("get_command_usage", {"command_name": "zzznotacommand"}, _ctx("bedrock"))
    assert obs.ok is False
    assert "未找到" in obs.summary or (obs.error and "未找到" in obs.error)


async def test_get_parameter_options_filters():
    obs = await _reg().execute("get_parameter_options", {"category": "items", "search_term": "sword"}, _ctx("bedrock"))
    assert isinstance(obs.to_tool_content(), str)
    assert obs.tool_name == "get_parameter_options"


async def test_edition_routing_java_loader_used(monkeypatch):
    # 断言 handler 用的是 get_loader(ctx.edition) 而非 bedrock 单例
    import backend.agentloop.tools.lookup as lookup_mod

    captured = {}

    class _FakeLoader:
        def get_command_doc(self, name):
            captured["edition_doc"] = name
            return {"name": name}

        def format_command_docs_compact(self, names):
            return f"[fake-java] {names[0]}"

    monkeypatch.setattr(lookup_mod, "get_loader", lambda edition: _FakeLoader() if edition == "java" else (_ for _ in ()).throw(AssertionError("应使用 java loader")))
    obs = await _reg().execute("get_command_usage", {"command_name": "give"}, _ctx("java"))
    assert "[fake-java]" in obs.summary


async def test_get_formatting_codes():
    obs = await _reg().execute("get_formatting_codes", {}, _ctx("bedrock"))
    assert isinstance(obs.to_tool_content(), str)
    assert obs.tool_name == "get_formatting_codes"
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/agentloop/test_lookup.py -v`
Expected: FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 实现**

先打开 `backend/tools/command_tools.py` 阅读 `_get_command_usage`(:124) / `_get_parameter_options`(:134) / `_get_formatting_codes`(:180) / `_search_wiki`(:188) 与 `TOOL_DEFINITIONS`(:25)。把前三者逻辑搬入新 handler，**把每处 `knowledge_loader` 换成 `loader = get_loader(ctx.edition)`**，格式化细节逐字保留。

Create `backend/agentloop/tools/lookup.py`:
```python
"""本地知识查询工具（edition 感知）。

复用 backend/tools/command_tools.py 的 4 个工具 schema（线级名称不变），
但所有数据访问改走 get_loader(ctx.edition)，修复既有 bedrock-only 单例的多版本错误。
"""

from __future__ import annotations

import json

from backend.agentloop.schemas import Observation
from backend.agentloop.tools.registry import ToolContext, ToolRegistry
from backend.knowledge.loader import get_loader
from backend.knowledge.wiki_search import wiki_searcher
from backend.tools.command_tools import TOOL_DEFINITIONS

# 从既有 TOOL_DEFINITIONS 按名取出 4 个 schema（线级契约不变）
_SCHEMAS = {d["function"]["name"]: d for d in TOOL_DEFINITIONS}

MAX_ENTRIES = 50


async def handle_get_command_usage(args: dict, ctx: ToolContext) -> Observation:
    name = str(args.get("command_name", "")).strip().lstrip("/").lower()
    loader = get_loader(ctx.edition)
    doc = loader.get_command_doc(name)
    if not doc:
        return Observation(
            tool_name="get_command_usage", ok=False,
            summary=f"未找到命令 '{name}' 的文档。请检查命令名称是否正确。",
        )
    text = loader.format_command_docs_compact([name])
    return Observation(tool_name="get_command_usage", ok=True, summary=text)


async def handle_get_parameter_options(args: dict, ctx: ToolContext) -> Observation:
    category = str(args.get("category", "")).strip().lower()
    search_term = args.get("search_term")
    loader = get_loader(ctx.edition)
    entries = loader.get_id_file(category)
    if not entries:
        available = loader.get_id_categories()
        return Observation(
            tool_name="get_parameter_options", ok=False,
            summary=f"未找到类别 '{category}'。可用类别: {', '.join(available)}",
        )
    if search_term:
        term = str(search_term).lower()
        filtered = [e for e in entries if term in json.dumps(e, ensure_ascii=False).lower()]
        if not filtered:
            return Observation(
                tool_name="get_parameter_options", ok=True,
                summary=f"在 '{category}' 中未找到与 '{search_term}' 匹配的条目。共 {len(entries)} 个条目。",
                data={"category": category, "count": 0},
            )
        entries = filtered
    lines = []
    for entry in entries[:MAX_ENTRIES]:
        if isinstance(entry, dict):
            entry_id = entry.get("id", entry.get("name", ""))
            desc = entry.get("description") or entry.get("name_cn") or entry.get("name", "")
            if desc and desc.lower().replace(" ", "_") != entry_id.lower():
                lines.append(f"- {entry_id}: {desc}")
            else:
                lines.append(f"- {entry_id}")
        elif isinstance(entry, str):
            lines.append(f"- {entry}")
    header = f"## {category} ({len(entries)} 条"
    if len(entries) > MAX_ENTRIES:
        header += f"，显示前 {MAX_ENTRIES} 条"
    header += ")"
    summary = header + "\n" + "\n".join(lines)
    return Observation(
        tool_name="get_parameter_options", ok=True, summary=summary,
        data={"category": category, "count": len(entries)},
    )


async def handle_get_formatting_codes(args: dict, ctx: ToolContext) -> Observation:
    loader = get_loader(ctx.edition)
    text = loader.format_formatting_codes_for_prompt()
    if not text:
        text = "格式代码数据不可用。基本颜色: §0-§f (16色), §g-§u (基岩版材质色), §k混淆 §l加粗 §o斜体 §r重置"
    return Observation(tool_name="get_formatting_codes", ok=True, summary=text)


async def handle_search_wiki(args: dict, ctx: ToolContext) -> Observation:
    query = str(args.get("query", "")).strip()
    category = args.get("category")
    if not query:
        return Observation(tool_name="search_wiki", ok=False, summary="请提供搜索关键词。")
    stats = wiki_searcher.get_stats()
    if not stats.get("initialized"):
        return Observation(
            tool_name="search_wiki", ok=True,
            summary="Wiki知识库未初始化。请参考你已有的知识回答。",
            data={"hits": []},
        )
    results = wiki_searcher.search(query, category=category)
    if not results:
        return Observation(
            tool_name="search_wiki", ok=True,
            summary=f"未找到与 '{query}' 相关的百科内容。",
            data={"hits": []},
        )
    lines = [f"## 搜索结果: {query} ({len(results)} 条)\n"]
    for r in results:
        lines.append(f"### {r['title']}")
        if r.get("source"):
            lines.append(f"来源: {r['source']} | 分类: {r.get('category', '')}")
        if r.get("summary"):
            lines.append(f"摘要: {r['summary']}")
        if r.get("snippet"):
            lines.append(f"片段: {r['snippet']}")
        article = wiki_searcher.get_article(r["id"])
        if article and article.get("content"):
            content = article["content"]
            if len(content) > 800:
                content = content[:800] + "..."
            lines.append(f"内容: {content}")
        lines.append("")
    return Observation(
        tool_name="search_wiki", ok=True, summary="\n".join(lines),
        data={"hits": [{"id": r["id"], "title": r["title"]} for r in results]},
    )


def register_lookup_tools(reg: ToolRegistry) -> None:
    reg.register(_SCHEMAS["get_command_usage"], handle_get_command_usage)
    reg.register(_SCHEMAS["get_parameter_options"], handle_get_parameter_options)
    reg.register(_SCHEMAS["get_formatting_codes"], handle_get_formatting_codes)
    reg.register(_SCHEMAS["search_wiki"], handle_search_wiki)
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/agentloop/test_lookup.py -v`
Expected: PASS（6 passed）。若 `give` 命令在 bedrock loader 查不到，先 `​.venv/bin/python -c "from backend.knowledge.loader import get_loader; print(bool(get_loader('bedrock').get_command_doc('give')))"` 确认数据存在；为 True 时该测试有效。

- [ ] **Step 5: Commit**

```bash
git add backend/agentloop/tools/lookup.py tests/agentloop/test_lookup.py
git commit -m "feat(agentloop): edition 感知本地查询工具（修复 bedrock-only 单例）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: 校验即工具 validate.py

**Files:**
- Create: `backend/agentloop/tools/validate.py`
- Test: `tests/agentloop/test_validate.py`

**Interfaces:**
- Consumes: `backend.skills.command_validator`（`validate(commands, edition) -> list[dict]`，每项 `{command, valid, errors:[{type,message,suggestion}], warnings:[{message}]}`）；`backend.skills.structural_validator`（`validate(commands) -> list[ValidationResult]` + `format_feedback(...)`）；`ValidationReport`/`ValidationIssue`/`Observation`。
- Produces: `VALIDATE_COMMAND_SCHEMA`、`handle_validate_command(args, ctx)`、`make_validation_report(cmd_results, struct_results, struct_feedback) -> ValidationReport`、`register_validate_tool(reg)`。

**背景（关键）：** 先打开 `backend/skills/command_validator.py`（看 `validate` 返回每项的确切键）与 `backend/skills/structural_validator.py`（看 `validate` 返回的 `ValidationResult`/`ValidationError` dataclass 的**确切字段名**，以及 `format_feedback` 的签名与返回）。`make_validation_report` 把两者归一成 `ValidationReport`：把 command_validator 每项 `errors[]`→`ValidationIssue(severity="error", type=err["type"], message=err["message"], suggestion=err.get("suggestion",""))`，`warnings[]`→`severity="warning"`；把 structural 的每个错误同样并入（type 前缀 `structural`）。`feedback_text` 直接用 structural_validator 的 `format_feedback` 输出（保持既有 orchestrator 重试读取的文本形状）。`valid = error_count == 0`。

- [ ] **Step 1: 写失败测试**

Create `tests/agentloop/test_validate.py`:
```python
import pytest

from backend.agentloop.schemas import LoopBudget, ValidationReport
from backend.agentloop.tools.registry import ToolContext, ToolRegistry
from backend.agentloop.tools.validate import (
    make_validation_report,
    register_validate_tool,
)


def _ctx(edition="bedrock"):
    return ToolContext(edition=edition, budget=LoopBudget(), counters={})


def _reg():
    reg = ToolRegistry()
    register_validate_tool(reg)
    return reg


def test_make_report_merges_errors_and_warnings():
    cmd_results = [
        {"command": "/give @p bad_item", "valid": False,
         "errors": [{"type": "id", "message": "未知物品 bad_item", "suggestion": "diamond"}],
         "warnings": []},
        {"command": "/say hi", "valid": True, "errors": [], "warnings": [{"message": "可优化"}]},
    ]
    report = make_validation_report(cmd_results, struct_results=[], struct_feedback="")
    assert isinstance(report, ValidationReport)
    assert report.error_count == 1
    assert report.warning_count == 1
    assert report.valid is False
    sev = sorted(i.severity for i in report.issues)
    assert sev == ["error", "warning"]


def test_make_report_valid_when_no_errors():
    cmd_results = [{"command": "/say hi", "valid": True, "errors": [], "warnings": []}]
    report = make_validation_report(cmd_results, struct_results=[], struct_feedback="✅")
    assert report.valid is True
    assert report.error_count == 0
    assert report.feedback_text == "✅"


async def test_validate_tool_registers_and_runs():
    reg = _reg()
    assert "validate_command" in reg.names()
    obs = await reg.execute("validate_command", {"commands": ["/give @p diamond 1"]}, _ctx())
    assert isinstance(obs.to_tool_content(), str)
    assert "valid" in obs.data  # data 是 ValidationReport.model_dump()


async def test_validate_tool_accepts_single_command_string():
    reg = _reg()
    obs = await reg.execute("validate_command", {"command": "/give @p diamond 1"}, _ctx())
    assert obs.tool_name == "validate_command"
    assert "valid" in obs.data
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/agentloop/test_validate.py -v`
Expected: FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 实现**

阅读两个 validator 源文件确认确切字段后，Create `backend/agentloop/tools/validate.py`：
```python
"""校验即工具：把 command/structural 校验结果归一成 ValidationReport 作为 Observation。"""

from __future__ import annotations

from typing import Any

from backend.agentloop.schemas import Observation, ValidationIssue, ValidationReport
from backend.agentloop.tools.registry import ToolContext, ToolRegistry
from backend.skills import command_validator, structural_validator

VALIDATE_COMMAND_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "validate_command",
        "description": "校验一条或多条 Minecraft 命令的语法、ID 合法性与结构正确性。在输出最终命令前调用以自检并据错误修正。",
        "parameters": {
            "type": "object",
            "properties": {
                "commands": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "待校验的命令列表（含或不含 / 前缀均可）",
                },
            },
            "required": ["commands"],
        },
    },
}


def make_validation_report(
    cmd_results: list[dict],
    struct_results: list,
    struct_feedback: str,
) -> ValidationReport:
    issues: list[ValidationIssue] = []
    for r in cmd_results:
        cmd = r.get("command", "")
        for err in r.get("errors", []) or []:
            issues.append(ValidationIssue(
                command=cmd, type=str(err.get("type", "syntax")),
                message=str(err.get("message", "")),
                suggestion=str(err.get("suggestion", "") or ""),
                severity="error",
            ))
        for warn in r.get("warnings", []) or []:
            issues.append(ValidationIssue(
                command=cmd, type=str(warn.get("type", "warning")),
                message=str(warn.get("message", "")),
                suggestion=str(warn.get("suggestion", "") or ""),
                severity="warning",
            ))
    # structural_validator 的字段以源文件为准；把其错误并入（type 前缀 structural）。
    # 见 Step 3 前的「阅读」：用确切属性名替换下面的取值。
    issues.extend(_structural_issues(struct_results))

    error_count = sum(1 for i in issues if i.severity == "error")
    warning_count = sum(1 for i in issues if i.severity == "warning")
    return ValidationReport(
        valid=error_count == 0,
        error_count=error_count,
        warning_count=warning_count,
        issues=issues,
        feedback_text=struct_feedback or ("✅ 校验通过" if error_count == 0 else f"❌ {error_count} 个错误"),
    )


def _structural_issues(struct_results: list) -> list[ValidationIssue]:
    """把 structural_validator 的结果转 ValidationIssue。

    注意：structural_validator.validate 的返回是 dataclass 列表；
    实现时按源文件的确切字段名读取 command / errors / message。
    """
    out: list[ValidationIssue] = []
    for res in struct_results or []:
        command = getattr(res, "command", "") or ""
        for err in getattr(res, "errors", []) or []:
            out.append(ValidationIssue(
                command=command,
                type="structural",
                message=str(getattr(err, "message", err)),
                suggestion=str(getattr(err, "suggestion", "") or ""),
                severity="error",
            ))
    return out


async def handle_validate_command(args: dict, ctx: ToolContext) -> Observation:
    commands = args.get("commands")
    if commands is None and args.get("command"):
        commands = [args["command"]]
    if not commands:
        return Observation(tool_name="validate_command", ok=False, summary="请提供待校验的命令。")
    if isinstance(commands, str):
        commands = [commands]

    cmd_results = command_validator.validate(commands, ctx.edition)
    struct_results = structural_validator.validate(commands)
    struct_feedback = structural_validator.format_feedback(struct_results)

    report = make_validation_report(cmd_results, struct_results, struct_feedback)
    return Observation(
        tool_name="validate_command",
        ok=report.valid,
        summary=report.feedback_text,
        data=report.model_dump(),
    )


def register_validate_tool(reg: ToolRegistry) -> None:
    reg.register(VALIDATE_COMMAND_SCHEMA, handle_validate_command)
```

> 实现者注意：`command_validator` / `structural_validator` 的**调用形式**（是模块函数还是类实例方法、`format_feedback` 的确切签名）以源文件为准。若它们是类（如 `CommandValidator()`），在本模块顶部实例化单例后调用。`_structural_issues` 内的属性名（`command`/`errors`/`message`/`suggestion`）务必对照 `structural_validator.py` 的 dataclass 改成确切字段；测试 `test_validate_tool_registers_and_runs` 会跑真实 validator，字段错会失败。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/agentloop/test_validate.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 5: Commit**

```bash
git add backend/agentloop/tools/validate.py tests/agentloop/test_validate.py
git commit -m "feat(agentloop): 校验即工具 validate_command（command+structural 归一为 ValidationReport）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: url_guard 加 allow_loopback + SearXNG 客户端

**Files:**
- Modify: `backend/llm/url_guard.py`（加 `allow_loopback` 参数，向后兼容）
- Modify: `backend/config.py`（加 SearXNG 配置）
- Modify: `tests/llm/test_url_guard.py`（追加 allow_loopback 用例）
- Create: `backend/agentloop/searxng_client.py`
- Test: `tests/agentloop/test_searxng_client.py`

**Interfaces:**
- Consumes: `backend.llm.url_guard.assert_safe_outbound_url`（加 `allow_loopback`）；`httpx`；config。
- Produces:
  - `assert_safe_outbound_url(url, *, resolver=None, allow_loopback=False)`：`allow_loopback=True` 时允许环回（127.0.0.1/::1），其余受限段仍拒绝。默认 False，**既有调用方行为不变**。
  - `@dataclass WebHit(title, url, snippet, engine=None)`
  - `class SearXNGClient(base_url, *, timeout=4.0, max_results=5, http=None)` + `async search(query, *, categories=None) -> list[WebHit]`（local-first：先 url_guard(allow_loopback=True)，再 GET `{base_url}/search?q=&format=json`；任何失败→`[]` + warning，不抛）
  - `get_searxng_client() -> SearXNGClient | None`（`SEARXNG_URL` 为空→None）

- [ ] **Step 1: 给 url_guard 加 allow_loopback（先测试）**

在 `tests/llm/test_url_guard.py` 追加：
```python
def test_allow_loopback_permits_127():
    # allow_loopback=True：环回放行（用于运营方配置的本地 SearXNG）
    assert_safe_outbound_url(
        "http://127.0.0.1:8888/search", resolver=_resolver("127.0.0.1"), allow_loopback=True
    )


def test_allow_loopback_still_blocks_private():
    # 即便 allow_loopback，私有/链路本地仍拒绝
    with pytest.raises(UnsafeURLError):
        assert_safe_outbound_url(
            "http://x/search", resolver=_resolver("10.0.0.1"), allow_loopback=True
        )
    with pytest.raises(UnsafeURLError):
        assert_safe_outbound_url(
            "http://x/search", resolver=_resolver("169.254.169.254"), allow_loopback=True
        )


def test_default_still_blocks_loopback():
    with pytest.raises(UnsafeURLError):
        assert_safe_outbound_url("http://x/m", resolver=_resolver("127.0.0.1"))
```
Run: `.venv/bin/python -m pytest tests/llm/test_url_guard.py -k loopback -v` → 新增 `allow_loopback` 用例 FAIL（参数不存在）。

- [ ] **Step 2: 改 url_guard 实现**

修改 `backend/llm/url_guard.py`：`_is_blocked_ip` 增加 `allow_loopback` 参数；`assert_safe_outbound_url` 增加 `allow_loopback: bool = False` 并透传：
```python
def _is_blocked_ip(ip_str: str, *, allow_loopback: bool = False) -> bool:
    ip = ipaddress.ip_address(ip_str)
    if allow_loopback and ip.is_loopback:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def assert_safe_outbound_url(url: str, *, resolver=None, allow_loopback: bool = False) -> None:
    ...
    for ip in ips:
        if _is_blocked_ip(ip, allow_loopback=allow_loopback):
            raise UnsafeURLError(f"URL 指向受限地址 {ip}（host={host}）")
```
Run: `.venv/bin/python -m pytest tests/llm/test_url_guard.py -v` → 全绿（既有 + 新增）。

- [ ] **Step 3: 加 config + 写 SearXNG 客户端失败测试**

`backend/config.py` 追加：
```python
# SearXNG（联网搜索，软依赖）
SEARXNG_URL = os.environ.get("SEARXNG_URL", "")  # 空 ⇒ 联网搜索禁用
SEARXNG_TIMEOUT = float(os.environ.get("SEARXNG_TIMEOUT", "4.0"))
WEB_SEARCH_MAX_RESULTS = int(os.environ.get("WEB_SEARCH_MAX_RESULTS", "5"))
```
Create `tests/agentloop/test_searxng_client.py`:
```python
import httpx
import pytest
import respx

from backend.agentloop.searxng_client import SearXNGClient, WebHit


def _patch_resolver(monkeypatch, ip="127.0.0.1"):
    monkeypatch.setattr("backend.llm.url_guard._resolve_host", lambda host, port: [ip])


@respx.mock
async def test_search_parses_results(monkeypatch):
    _patch_resolver(monkeypatch)
    respx.get("http://127.0.0.1:8888/search").mock(
        return_value=httpx.Response(200, json={"results": [
            {"title": "T1", "url": "https://a", "content": "片段1", "engine": "ddg"},
            {"title": "T2", "url": "https://b", "content": "片段2"},
        ]})
    )
    client = SearXNGClient("http://127.0.0.1:8888", max_results=5)
    hits = await client.search("红石")
    assert [h.title for h in hits] == ["T1", "T2"]
    assert hits[0].url == "https://a" and hits[0].snippet == "片段1"
    assert isinstance(hits[0], WebHit)


@respx.mock
async def test_search_caps_max_results(monkeypatch):
    _patch_resolver(monkeypatch)
    respx.get("http://127.0.0.1:8888/search").mock(
        return_value=httpx.Response(200, json={"results": [
            {"title": f"T{i}", "url": f"https://{i}", "content": ""} for i in range(10)
        ]})
    )
    client = SearXNGClient("http://127.0.0.1:8888", max_results=3)
    hits = await client.search("x")
    assert len(hits) == 3


@respx.mock
async def test_timeout_returns_empty(monkeypatch):
    _patch_resolver(monkeypatch)
    respx.get("http://127.0.0.1:8888/search").mock(side_effect=httpx.ConnectTimeout("slow"))
    client = SearXNGClient("http://127.0.0.1:8888")
    assert await client.search("x") == []


@respx.mock
async def test_non_200_returns_empty(monkeypatch):
    _patch_resolver(monkeypatch)
    respx.get("http://127.0.0.1:8888/search").mock(return_value=httpx.Response(502))
    client = SearXNGClient("http://127.0.0.1:8888")
    assert await client.search("x") == []


async def test_unsafe_url_returns_empty(monkeypatch):
    # base_url 解析到公网外的私有地址（非环回）→ url_guard 拒 → []
    monkeypatch.setattr("backend.llm.url_guard._resolve_host", lambda host, port: ["10.0.0.5"])
    client = SearXNGClient("http://internal.evil/")
    assert await client.search("x") == []


def test_get_client_disabled_when_no_url(monkeypatch):
    import backend.agentloop.searxng_client as mod
    monkeypatch.setattr(mod, "SEARXNG_URL", "")
    # 强制重置单例缓存
    mod._client_singleton = None
    mod._client_resolved = False
    assert mod.get_searxng_client() is None
```

- [ ] **Step 4: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/agentloop/test_searxng_client.py -v`
Expected: FAIL（`ModuleNotFoundError`）。

- [ ] **Step 5: 实现 SearXNG 客户端**

Create `backend/agentloop/searxng_client.py`:
```python
"""SearXNG 联网搜索客户端（local-first，best-effort 软依赖）。

任何失败都返回 []（不抛进循环）；base_url 经 url_guard 校验（允许运营方配置的本地环回）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from backend.config import SEARXNG_TIMEOUT, SEARXNG_URL, WEB_SEARCH_MAX_RESULTS
from backend.llm.url_guard import UnsafeURLError, assert_safe_outbound_url

logger = logging.getLogger(__name__)


@dataclass
class WebHit:
    title: str
    url: str
    snippet: str
    engine: str | None = None


class SearXNGClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = SEARXNG_TIMEOUT,
        max_results: int = WEB_SEARCH_MAX_RESULTS,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_results = max_results
        self._http = http

    async def search(self, query: str, *, categories: str | None = None) -> list[WebHit]:
        url = self._base_url + "/search"
        try:
            # 允许运营方配置的本地环回 SearXNG；其余内网/元数据仍拒绝
            assert_safe_outbound_url(url, allow_loopback=True)
        except UnsafeURLError as exc:
            logger.warning("SearXNG base_url 不安全，跳过联网搜索：%s", exc)
            return []

        params = {"q": query, "format": "json"}
        if categories:
            params["categories"] = categories
        try:
            if self._http is not None:
                resp = await self._http.get(url, params=params, timeout=self._timeout)
            else:
                async with httpx.AsyncClient(trust_env=False, timeout=self._timeout) as client:
                    resp = await client.get(url, params=params, follow_redirects=False)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001 - best-effort：任何失败都降级为空
            logger.warning("SearXNG 搜索失败（query=%s）：%s", query, exc)
            return []

        results = payload.get("results", []) if isinstance(payload, dict) else []
        hits: list[WebHit] = []
        for r in results[: self._max_results]:
            if not isinstance(r, dict):
                continue
            hits.append(WebHit(
                title=str(r.get("title", "")),
                url=str(r.get("url", "")),
                snippet=str(r.get("content", "")),
                engine=r.get("engine"),
            ))
        return hits


_client_singleton: SearXNGClient | None = None
_client_resolved: bool = False


def get_searxng_client() -> SearXNGClient | None:
    """返回单例客户端；SEARXNG_URL 为空时返回 None（联网搜索禁用）。"""
    global _client_singleton, _client_resolved
    if not _client_resolved:
        _client_singleton = SearXNGClient(SEARXNG_URL) if SEARXNG_URL else None
        _client_resolved = True
    return _client_singleton
```

- [ ] **Step 6: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/agentloop/test_searxng_client.py tests/llm/test_url_guard.py -v`
Expected: PASS（searxng 6 + url_guard 既有+3 新增）。

- [ ] **Step 7: Commit**

```bash
git add backend/llm/url_guard.py backend/config.py backend/agentloop/searxng_client.py tests/agentloop/test_searxng_client.py tests/llm/test_url_guard.py
git commit -m "feat(agentloop): SearXNG 客户端（local-first best-effort）+ url_guard allow_loopback

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: search_web 工具 search.py

**Files:**
- Create: `backend/agentloop/tools/search.py`
- Test: `tests/agentloop/test_search.py`

**Interfaces:**
- Consumes: `backend.agentloop.searxng_client.get_searxng_client`；`ToolContext`/`Observation`/`ToolRegistry`。
- Produces: `SEARCH_WEB_SCHEMA`、`handle_search_web(args, ctx)`、`register_search_tools(reg)`。子预算：`ctx.counters["search_web"]` 超过 `ctx.budget.max_search_web_calls` → 返回 `ok=False` 提示已达上限（不再搜）。SearXNG 禁用（client=None）→ `ok=False, summary="联网搜索未启用"`。有结果/0 结果都 `ok=True`。

- [ ] **Step 1: 写失败测试**

Create `tests/agentloop/test_search.py`:
```python
import pytest

import backend.agentloop.tools.search as search_mod
from backend.agentloop.schemas import LoopBudget
from backend.agentloop.searxng_client import WebHit
from backend.agentloop.tools.registry import ToolContext, ToolRegistry
from backend.agentloop.tools.search import register_search_tools


def _ctx(counters=None):
    return ToolContext(edition="bedrock", budget=LoopBudget(max_search_web_calls=2), counters=counters or {})


def _reg():
    reg = ToolRegistry()
    register_search_tools(reg)
    return reg


class _FakeClient:
    def __init__(self, hits):
        self._hits = hits
        self.calls = 0

    async def search(self, query, *, categories=None):
        self.calls += 1
        return self._hits


async def test_search_web_returns_hits(monkeypatch):
    fake = _FakeClient([WebHit("T", "https://a", "片段")])
    monkeypatch.setattr(search_mod, "get_searxng_client", lambda: fake)
    obs = await _reg().execute("search_web", {"query": "红石"}, _ctx())
    assert obs.ok is True
    assert "T" in obs.summary
    assert obs.data["hits"][0]["url"] == "https://a"


async def test_search_web_zero_hits_still_ok(monkeypatch):
    monkeypatch.setattr(search_mod, "get_searxng_client", lambda: _FakeClient([]))
    obs = await _reg().execute("search_web", {"query": "x"}, _ctx())
    assert obs.ok is True
    assert obs.data["hits"] == []


async def test_search_web_disabled(monkeypatch):
    monkeypatch.setattr(search_mod, "get_searxng_client", lambda: None)
    obs = await _reg().execute("search_web", {"query": "x"}, _ctx())
    assert obs.ok is False
    assert "未启用" in obs.summary


async def test_search_web_sub_budget(monkeypatch):
    fake = _FakeClient([WebHit("T", "https://a", "片段")])
    monkeypatch.setattr(search_mod, "get_searxng_client", lambda: fake)
    counters = {}
    ctx = _ctx(counters)
    await _reg().execute("search_web", {"query": "1"}, ctx)
    await _reg().execute("search_web", {"query": "2"}, ctx)
    obs3 = await _reg().execute("search_web", {"query": "3"}, ctx)  # 第 3 次超预算（max=2）
    assert obs3.ok is False
    assert "上限" in obs3.summary
    assert fake.calls == 2  # 第三次未真正调用
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/agentloop/test_search.py -v`
Expected: FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 实现**

Create `backend/agentloop/tools/search.py`:
```python
"""联网搜索工具 search_web（SearXNG，本地优先，best-effort，带子预算）。"""

from __future__ import annotations

from typing import Any

from backend.agentloop.schemas import Observation
from backend.agentloop.searxng_client import get_searxng_client
from backend.agentloop.tools.registry import ToolContext, ToolRegistry

SEARCH_WEB_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": "当本地命令文档与百科都无法解答时，搜索外部网络获取参考信息。优先使用本地知识库，仅在必要时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
            },
            "required": ["query"],
        },
    },
}


async def handle_search_web(args: dict, ctx: ToolContext) -> Observation:
    used = ctx.counters.get("search_web", 0)
    if used >= ctx.budget.max_search_web_calls:
        return Observation(
            tool_name="search_web", ok=False,
            summary=f"联网搜索已达本轮上限（{ctx.budget.max_search_web_calls} 次），请基于已有信息给出答案。",
        )

    client = get_searxng_client()
    if client is None:
        return Observation(
            tool_name="search_web", ok=False,
            summary="联网搜索未启用（未配置 SEARXNG_URL）。请基于本地知识回答。",
            data={"hits": []},
        )

    query = str(args.get("query", "")).strip()
    if not query:
        return Observation(tool_name="search_web", ok=False, summary="请提供搜索关键词。")

    ctx.counters["search_web"] = used + 1
    hits = await client.search(query)
    if not hits:
        return Observation(
            tool_name="search_web", ok=True,
            summary=f"未找到与 '{query}' 相关的外部结果。",
            data={"hits": []},
        )
    lines = [f"## 联网搜索: {query} ({len(hits)} 条)\n"]
    for h in hits:
        lines.append(f"### {h.title}")
        lines.append(f"链接: {h.url}")
        if h.snippet:
            lines.append(f"摘要: {h.snippet}")
        lines.append("")
    return Observation(
        tool_name="search_web", ok=True, summary="\n".join(lines),
        data={"hits": [{"title": h.title, "url": h.url, "snippet": h.snippet} for h in hits]},
    )


def register_search_tools(reg: ToolRegistry) -> None:
    reg.register(SEARCH_WEB_SCHEMA, handle_search_web)
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/agentloop/test_search.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 5: Commit**

```bash
git add backend/agentloop/tools/search.py tests/agentloop/test_search.py
git commit -m "feat(agentloop): search_web 工具（SearXNG，带子预算与禁用降级）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: finish 工具 + build_default_registry 装配

**Files:**
- Create: `backend/agentloop/tools/finish.py`
- Test: `tests/agentloop/test_finish_and_registry.py`

**Interfaces:**
- Consumes: 所有 `register_*` 函数（lookup/validate/search/finish）。
- Produces: `FINISH_SCHEMA`、`handle_finish(args, ctx)`（归一 `{reason, final_answer}`；非法 reason→`give_up`）、`register_finish_tool(reg)`、`build_default_registry() -> ToolRegistry`（装配 7 个工具）。

- [ ] **Step 1: 写失败测试**

Create `tests/agentloop/test_finish_and_registry.py`:
```python
import pytest

from backend.agentloop.schemas import LoopBudget
from backend.agentloop.tools.finish import build_default_registry, register_finish_tool
from backend.agentloop.tools.registry import ToolContext, ToolRegistry


def _ctx():
    return ToolContext(edition="bedrock", budget=LoopBudget(), counters={})


async def test_finish_normalizes_done():
    reg = ToolRegistry()
    register_finish_tool(reg)
    obs = await reg.execute("finish", {"reason": "done", "final_answer": "/give @p diamond"}, _ctx())
    assert obs.data["reason"] == "done"
    assert obs.data["final_answer"] == "/give @p diamond"


async def test_finish_invalid_reason_falls_back_giveup():
    reg = ToolRegistry()
    register_finish_tool(reg)
    obs = await reg.execute("finish", {"reason": "nonsense", "final_answer": "x"}, _ctx())
    assert obs.data["reason"] == "give_up"


def test_build_default_registry_has_seven_tools():
    reg = build_default_registry()
    assert reg.names() == {
        "get_command_usage", "get_parameter_options", "get_formatting_codes",
        "search_wiki", "validate_command", "search_web", "finish",
    }
    # get_schemas 与 chat_with_tools 的 tools= 形状兼容
    schemas = reg.get_schemas()
    assert len(schemas) == 7
    assert all(s["type"] == "function" and "name" in s["function"] for s in schemas)


async def test_build_default_registry_dispatches_finish():
    reg = build_default_registry()
    obs = await reg.execute("finish", {"reason": "ask_user", "final_answer": "你想要钻石剑还是铁剑？"}, _ctx())
    assert obs.data["reason"] == "ask_user"
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/agentloop/test_finish_and_registry.py -v`
Expected: FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 实现**

Create `backend/agentloop/tools/finish.py`:
```python
"""finish 终止工具 + 默认注册表装配。

finish 是终止动作：循环检测到 name=='finish' 时据其 reason 终止；本 handler 只归一参数。
"""

from __future__ import annotations

from typing import Any

from backend.agentloop.schemas import Observation
from backend.agentloop.tools.lookup import register_lookup_tools
from backend.agentloop.tools.registry import ToolContext, ToolRegistry
from backend.agentloop.tools.search import register_search_tools
from backend.agentloop.tools.validate import register_validate_tool

_VALID_REASONS = {"done", "ask_user", "give_up"}

FINISH_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "finish",
        "description": "结束任务并给出最终结果。done=已生成命令；ask_user=需要用户澄清；give_up=无法完成。",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "enum": ["done", "ask_user", "give_up"]},
                "final_answer": {
                    "type": "string",
                    "description": "最终输出。done 时为符合输出规范的结果；ask_user 时为追问文本。",
                },
            },
            "required": ["reason", "final_answer"],
        },
    },
}


async def handle_finish(args: dict, ctx: ToolContext) -> Observation:
    reason = str(args.get("reason", "")).strip()
    if reason not in _VALID_REASONS:
        reason = "give_up"
    final_answer = str(args.get("final_answer", ""))
    return Observation(
        tool_name="finish", ok=True,
        summary=f"finish: {reason}",
        data={"reason": reason, "final_answer": final_answer},
    )


def register_finish_tool(reg: ToolRegistry) -> None:
    reg.register(FINISH_SCHEMA, handle_finish)


def build_default_registry() -> ToolRegistry:
    """装配 7 个工具的默认注册表（每个 AgentLoop 构造时调用一次，廉价）。"""
    reg = ToolRegistry()
    register_lookup_tools(reg)     # 4 个本地查询
    register_validate_tool(reg)    # validate_command
    register_search_tools(reg)     # search_web
    register_finish_tool(reg)      # finish
    return reg
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/agentloop/test_finish_and_registry.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 5: 全量回归**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS（Phase 1 的 46 + 本期 agentloop 全部用例）。

- [ ] **Step 6: Commit**

```bash
git add backend/agentloop/tools/finish.py tests/agentloop/test_finish_and_registry.py
git commit -m "feat(agentloop): finish 终止工具 + build_default_registry 装配 7 工具

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage（对照设计 spec 第 5.3 工具 + 第 5.5 SearXNG + 决策②③）**
- ToolRegistry + 7 工具（lookup×4 / validate / search_web / finish）→ Tasks 2-7 ✓
- 校验即工具（结构化 ValidationReport）→ Task 4 ✓
- SearXNG local-first + best-effort + url_guard 复用 → Task 5 ✓
- edition 感知本地检索（修复 bedrock-only 单例）→ Task 3 ✓（决策③：词法/结构化为权威核心）
- 工具线级名称不变（向后兼容 LLM 契约）→ Task 3/全局约束 ✓
- LoopBudget / Observation / StepResult / AgentOutcome 契约 → Task 1 ✓（供 2B 的 loop/step 消费）
- 不触碰运行路径（loop/wiring 留到 2B）→ 全局约束 ✓

**2. Placeholder scan**：无 TBD/TODO。唯一「需对照源文件确认字段」的点是 Task 4 的 `_structural_issues`（structural_validator 的 dataclass 字段名）——已明确指示实现者先读 `structural_validator.py` 并给出 `getattr` 兜底 + 真实 validator 测试兜底，非占位符。

**3. Type consistency**：
- `Observation(tool_name, ok, summary, data, error)` 在 schemas 定义，所有 handler 与 registry 按此构造 ✓
- `ToolContext(edition, budget, counters)` 在 registry 定义，所有 handler 按此读取（`ctx.edition` / `ctx.budget.max_search_web_calls` / `ctx.counters`）✓
- `register_*` 签名统一 `(reg: ToolRegistry) -> None`；`build_default_registry` 调用全部四个 ✓
- 工具 wire 名称集合在 Task 7 测试中固定为 7 个，与各 register 一致 ✓
- `ValidationReport.model_dump()` 进 `Observation.data`，Task 4 测试断言 `"valid" in obs.data` ✓
- `assert_safe_outbound_url(..., allow_loopback=)` 新签名：SearXNG 客户端传 True，既有 catalog 调用不传（默认 False，行为不变）✓

无不一致；无遗漏本期范围内 spec 项。
