# Phase 2B — AgentLoop + LLMStep + chat 单任务接线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建成统一 Agent 循环本体（`AgentLoop`）+ provider 无关的 `LLMStep`（原生工具 / 提示式模拟），并把 chat **单任务**路径经 `AgentLoop` 接线——藏在 `USE_AGENT_LOOP` 开关后（默认关），多任务路径**逐字不变**。

**Architecture:** Phase 2A 已交付 `backend/agentloop/`（schemas / ToolRegistry / build_default_registry 7 工具）。本期新增 `single_task.py`（从 TaskAgent **移出**单任务 prompt 构建 / 输出解析 / 校验逻辑，TaskAgent 改为薄委托——保证唯一实现、字节级一致）、`step.py`（NativeToolStep + PromptedToolStep）、`loop.py`（AgentLoop.run）。orchestrator 在单任务分支前插入一个开关守卫，调用新 `_run_single_task_loop`，发出**与现有逐字相同**的 SSE 事件。

**Tech Stack:** Python 3.11、asyncio、Pydantic/dataclass；测试 pytest + pytest-asyncio（已装）。

## Global Constraints

- 语言：注释/docstring/面向用户字符串中文。
- **多任务路径零改动**：新分支只在 `USE_AGENT_LOOP and is_single and len(tasks)==1` 时触发；其余路径（多任务、暂停、resume）到达的旧代码逐字不变。用 `git diff` 自查除单点守卫插入外，orchestrator 旧单/多任务代码不变。
- **解析字节级一致（合并门槛）**：`single_task.parse_output` 必须是**唯一实现**，TaskAgent 旧方法改为委托它。用「老 vs 新」冻结语料 parity 测试守门。
- **edition 不对称保留**：旧 `_run_validation` 调 `command_validator.validate(cmd_lines)` **不带 edition**（task_agent.py:1210）——`single_task.run_validation` **保持不带 edition**（parity）。循环自己的 `validate_command` 工具才带 edition（已在 2A）。本期不要「统一」它们。
- **provider 工具消息分叉**：Native 用 `{"role":"tool","tool_call_id":id,"content":str}`；Prompted（GLM 等 supports_tools=False）把 observation 折叠成 `{"role":"user","content":...}`（非工具模型不接受 tool 角色）。
- **每次 run 全新 ToolContext**：`counters={}` 在 `AgentLoop.run` 内构造，绝不跨调用复用（否则 `search_web` 子预算跨请求泄漏）。
- **finish 判定靠 `data["reason"]`**，不靠 `Observation.ok`（finish 永远 ok=True）。
- 开关默认 **关**：`USE_AGENT_LOOP=false`。合并后在 staging 用 env 翻开、看 SSE parity 再决定默认开。
- 提交频繁，提交信息中文，结尾附 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。测试从仓库根 `.venv/bin/python -m pytest`，输出 pristine。

---

## File Structure

**新建**
- `backend/agentloop/single_task.py` — `build_single_task_messages` / `parse_output` / `run_validation`（从 TaskAgent 移出的唯一实现）
- `backend/agentloop/step.py` — `LLMStep`(ABC) / `NativeToolStep` / `PromptedToolStep` / `build_step(client)`
- `backend/agentloop/loop.py` — `AgentLoop`
- `tests/agentloop/test_single_task.py` / `test_step.py` / `test_loop.py` / `tests/agentloop/test_orchestrator_loop.py`

**修改**
- `backend/config.py` — `USE_AGENT_LOOP` / `AGENT_LOOP_MAX_ROUNDS` / `AGENT_LOOP_MAX_TOKENS`
- `backend/agents/task_agent.py` — 把 `_build_prompt`/`_parse_output`/`_looks_like_conversation`/`_normalize_output`/`_run_validation` 改为委托 `single_task` 的薄包装（行为不变）
- `backend/orchestrator/orchestrator.py` — 单任务守卫插入 + `_run_single_task_loop` + `_outcome_to_result`

---

## Task 1: 配置开关

**Files:** Modify `backend/config.py`；Test `tests/agentloop/test_config_flags.py`

**Interfaces:** Produces `USE_AGENT_LOOP: bool`（默认 False）、`AGENT_LOOP_MAX_ROUNDS: int`（默认 8）、`AGENT_LOOP_MAX_TOKENS: int`（默认 = `TASK_AGENT_MAX_TOKENS`）。

- [ ] **Step 1: 写失败测试**

Create `tests/agentloop/test_config_flags.py`:
```python
import importlib


def test_flags_default(monkeypatch):
    for k in ("USE_AGENT_LOOP", "AGENT_LOOP_MAX_ROUNDS", "AGENT_LOOP_MAX_TOKENS"):
        monkeypatch.delenv(k, raising=False)
    import backend.config as cfg
    importlib.reload(cfg)
    assert cfg.USE_AGENT_LOOP is False
    assert cfg.AGENT_LOOP_MAX_ROUNDS == 8
    assert cfg.AGENT_LOOP_MAX_TOKENS == cfg.TASK_AGENT_MAX_TOKENS


def test_use_agent_loop_truthy(monkeypatch):
    monkeypatch.setenv("USE_AGENT_LOOP", "true")
    import backend.config as cfg
    importlib.reload(cfg)
    assert cfg.USE_AGENT_LOOP is True
    monkeypatch.setenv("USE_AGENT_LOOP", "0")
    importlib.reload(cfg)
    assert cfg.USE_AGENT_LOOP is False
    # reload 收尾，避免污染其它测试
    monkeypatch.delenv("USE_AGENT_LOOP", raising=False)
    importlib.reload(cfg)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/agentloop/test_config_flags.py -v` → FAIL（属性不存在）。

- [ ] **Step 3: 实现**

在 `backend/config.py` 的 `TASK_AGENT_MAX_TOKENS` 定义之后新增：
```python
# 统一 Agent 循环（Phase 2B）
USE_AGENT_LOOP = os.environ.get("USE_AGENT_LOOP", "false").lower() in ("1", "true", "yes")
AGENT_LOOP_MAX_ROUNDS = int(os.environ.get("AGENT_LOOP_MAX_ROUNDS", "8"))
AGENT_LOOP_MAX_TOKENS = int(os.environ.get("AGENT_LOOP_MAX_TOKENS", str(TASK_AGENT_MAX_TOKENS)))
```
（若 `TASK_AGENT_MAX_TOKENS` 定义在更下方，把以上三行放到它之后。）

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/agentloop/test_config_flags.py -v` → PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/config.py tests/agentloop/test_config_flags.py
git commit -m "feat(agentloop): USE_AGENT_LOOP 开关 + AGENT_LOOP_MAX_ROUNDS/TOKENS 配置

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: 抽出单任务共享逻辑 single_task.py（含 parity 门槛）

**Files:** Create `backend/agentloop/single_task.py`；Modify `backend/agents/task_agent.py`；Test `tests/agentloop/test_single_task.py`

**Interfaces:**
- `build_single_task_messages(user_request, output_type, command_directory, *, edition="bedrock", ambiguous=False) -> list[dict]`
- `parse_output(raw: str, output_type: str) -> dict`
- `run_validation(content_data: dict) -> None`（原地变更）

**做法（关键）：** **把逻辑移到 `single_task.py` 做唯一实现**，然后把 TaskAgent 的对应方法改成**薄委托包装**。先打开 `backend/agents/task_agent.py` 通读这些段落并整体搬运（保留所有中文关键词表、模板选择、归一逻辑逐字）：
- 单任务消息组装：`_build_prompt`（约 :1071-1083）+ 调用处的 system/user 组装（约 :949-959，含 `ambiguity_hint` :952、`command_directory` 注入、edition 分支 :1073-1078）。
- 输出解析：`_parse_output`（:1085-1124）+ `_looks_like_conversation`（:1126-1148，中文关键词表 :1130-1136 逐字保留）+ `_normalize_output`（:1150-1195）。
- 校验：`_run_validation`（:1197-1240）。**保持 `command_validator.validate(cmd_lines)` 不带 edition**（:1210）——这是 parity 要求，勿改。
- 大模板常量 `_BASE_TEMPLATE*` / `_TYPE_SECTIONS*` 留在 task_agent.py；`single_task.build_single_task_messages` 从 `backend.agents.task_agent` import 它们（或反向：把常量也移到 single_task 再让 task_agent import）。择一，保证无循环 import。

搬运后，TaskAgent 旧方法改为：
```python
def _parse_output(self, raw, output_type):
    from backend.agentloop import single_task
    return single_task.parse_output(raw, output_type)
# 其余同理委托
```

- [ ] **Step 1: 写 parity 失败测试**

Create `tests/agentloop/test_single_task.py`（先冻结一份老实现的语料对照）：
```python
import pytest

from backend.agentloop import single_task

# 冻结语料：覆盖 合法JSON / 代码围栏JSON / 中文对话 / 纯命令 / 垃圾
RAW_CASES = [
    ('{"type":"single_command","command":{"command":"/give @p diamond 1","explanation":"给钻石"}}', "simple_command"),
    ('```json\n{"type":"single_command","command":{"command":"/say hi","explanation":"说"}}\n```', "simple_command"),
    ("你想要钻石剑还是铁剑呢？请告诉我具体需求。", "simple_command"),
    ("/give @p diamond 1", "simple_command"),
    ("这是一段没有结构的废话", "simple_command"),
]


@pytest.mark.parametrize("raw,otype", RAW_CASES)
def test_parse_output_parity_with_legacy(raw, otype):
    # 老实现（委托前的等价路径）：用 TaskAgent 实例方法作为 oracle
    from backend.agents.task_agent import TaskAgent
    legacy = TaskAgent.__new__(TaskAgent)  # 不跑 __init__，仅借纯函数方法
    expected = legacy._parse_output(raw, otype)
    got = single_task.parse_output(raw, otype)
    assert got == expected


def test_looks_like_conversation_truth_table():
    assert single_task.parse_output("你需要我帮你确认哪个版本？", "simple_command").get("type") == "conversation"
    assert single_task.parse_output("/give @p stone", "simple_command").get("type") != "conversation"


def test_build_messages_java_template():
    msgs = single_task.build_single_task_messages("造个传送", "simple_command", "（命令目录）", edition="java")
    joined = " ".join(m["content"] for m in msgs)
    assert "Java" in joined or "java" in joined


def test_build_messages_ambiguous_hint():
    base = single_task.build_single_task_messages("x", "simple_command", "", ambiguous=False)
    amb = single_task.build_single_task_messages("x", "simple_command", "", ambiguous=True)
    assert len("".join(m["content"] for m in amb)) > len("".join(m["content"] for m in base))


def test_run_validation_mutates_in_place():
    data = {"type": "single_command", "command": {"command": "/give @p diamond 1", "explanation": ""}}
    out = single_task.run_validation(data)
    assert out is None
    assert "validation" in data["command"]
```

> 注意：`test_parse_output_parity_with_legacy` 在**搬运前**会先失败（`single_task` 不存在）；搬运后，因 TaskAgent 已委托同一实现，老 oracle 与新函数恒等 —— 若不恒等说明搬运漏改，parity 门槛即报警。`TaskAgent.__new__` 跳过 `__init__`，仅当这些方法是纯函数（不读 `self` 状态）时成立；若它们读了 `self.x`，实现者需把那些状态改为函数入参（在 single_task 里），并在报告中说明。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/agentloop/test_single_task.py -v` → FAIL（模块不存在）。

- [ ] **Step 3: 实现**

按「做法」搬运逻辑到 `backend/agentloop/single_task.py`，并把 TaskAgent 方法改为委托。**若某方法读 `self` 状态**（如 `self.edition`/`self.client`），把该状态提升为 `single_task` 函数参数，并让 TaskAgent 包装传入 `self.x`。

- [ ] **Step 4: 运行确认通过 + TaskAgent 回归**

Run: `.venv/bin/python -m pytest tests/agentloop/test_single_task.py -v` → PASS。
Run: `.venv/bin/python -m pytest tests/ -q` → 全绿（既有用例不变，证明委托无回归）。

- [ ] **Step 5: Commit**

```bash
git add backend/agentloop/single_task.py backend/agents/task_agent.py tests/agentloop/test_single_task.py
git commit -m "refactor(agentloop): 抽出单任务 prompt/parse/validate 为唯一实现，TaskAgent 委托（parity 门槛）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: NativeToolStep + build_step

**Files:** Create `backend/agentloop/step.py`；Test `tests/agentloop/test_step.py`

**Interfaces:**
- `class LLMStep`(ABC): `async run(messages, tool_schemas) -> StepResult`；`format_observation(call: ToolCall, obs: Observation) -> dict`
- `class NativeToolStep(LLMStep)`：`__init__(client)`；`run` 包 `client.chat_with_tools`；`format_observation` 返回 `{"role":"tool","tool_call_id":call.id,"content":obs.to_tool_content()}`
- `build_step(client) -> LLMStep`：依 `get_provider(client.provider_id).supports_tools`（None→乐观 Native，镜像 task_agent.py:909-916）选 Native/Prompted

- [ ] **Step 1: 写失败测试**

Create `tests/agentloop/test_step.py`:
```python
import types

from backend.agentloop.schemas import Observation, ToolCall
from backend.agentloop.step import NativeToolStep, PromptedToolStep, build_step


class _NativeClient:
    provider_id = "deepseek"

    def __init__(self, msg):
        self._msg = msg

    async def chat_with_tools(self, messages, tools, *, max_tokens=None):
        return {"message": self._msg}


async def test_native_maps_tool_calls():
    msg = {"role": "assistant", "content": "", "thinking": "想",
           "tool_calls": [{"id": "c1", "type": "function",
                           "function": {"name": "get_command_usage", "arguments": {"command_name": "give"}}}]}
    sr = await NativeToolStep(_NativeClient(msg)).run([], [])
    assert sr.tool_calls[0].id == "c1"
    assert sr.tool_calls[0].name == "get_command_usage"
    assert sr.tool_calls[0].arguments == {"command_name": "give"}  # dict, 非 str
    assert sr.thinking == "想"
    assert sr.raw_assistant_msg is msg


async def test_native_no_tool_calls():
    sr = await NativeToolStep(_NativeClient({"role": "assistant", "content": "答案", "thinking": ""})).run([], [])
    assert sr.tool_calls == []
    assert sr.content == "答案"


def test_native_format_observation():
    step = NativeToolStep(_NativeClient({}))
    msg = step.format_observation(ToolCall("c1", "x", {}), Observation("x", True, "结果"))
    assert msg == {"role": "tool", "tool_call_id": "c1", "content": "结果"}


def test_build_step_picks_native_for_tool_provider(monkeypatch):
    import backend.agentloop.step as step_mod
    monkeypatch.setattr(step_mod, "get_provider", lambda pid: types.SimpleNamespace(supports_tools=True))
    assert isinstance(build_step(_NativeClient({})), NativeToolStep)


def test_build_step_picks_prompted_for_glm(monkeypatch):
    import backend.agentloop.step as step_mod
    monkeypatch.setattr(step_mod, "get_provider", lambda pid: types.SimpleNamespace(supports_tools=False))
    assert isinstance(build_step(_NativeClient({})), PromptedToolStep)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/agentloop/test_step.py -v` → FAIL。

- [ ] **Step 3: 实现 NativeToolStep + build_step（PromptedToolStep 占位到 Task 4 完整实现）**

Create `backend/agentloop/step.py`:
```python
"""LLMStep：provider 无关的「走一步」抽象。Native=原生工具调用；Prompted=提示式模拟。"""

from __future__ import annotations

import abc
from typing import Any

from backend.agentloop.schemas import Observation, StepResult, ToolCall
from backend.config import AGENT_LOOP_MAX_TOKENS
from backend.utils.providers import get_provider


class LLMStep(abc.ABC):
    @abc.abstractmethod
    async def run(self, messages: list[dict[str, Any]], tool_schemas: list[dict[str, Any]]) -> StepResult: ...

    @abc.abstractmethod
    def format_observation(self, call: ToolCall, obs: Observation) -> dict[str, Any]: ...


class NativeToolStep(LLMStep):
    def __init__(self, client) -> None:
        self._client = client

    async def run(self, messages, tool_schemas) -> StepResult:
        resp = await self._client.chat_with_tools(messages, tool_schemas, max_tokens=AGENT_LOOP_MAX_TOKENS)
        msg = resp["message"]
        tool_calls = [
            ToolCall(id=tc["id"], name=tc["function"]["name"], arguments=tc["function"]["arguments"])
            for tc in msg.get("tool_calls", [])
        ]
        return StepResult(
            content=msg.get("content", ""), thinking=msg.get("thinking", ""),
            tool_calls=tool_calls, raw_assistant_msg=msg,
        )

    def format_observation(self, call: ToolCall, obs: Observation) -> dict[str, Any]:
        return {"role": "tool", "tool_call_id": call.id, "content": obs.to_tool_content()}


def build_step(client) -> LLMStep:
    provider = get_provider(getattr(client, "provider_id", ""))
    supports = getattr(provider, "supports_tools", True) if provider else True
    if supports:
        return NativeToolStep(client)
    return PromptedToolStep(client)


# PromptedToolStep 在 Task 4 完整实现；此处先占位以满足 build_step 的引用。
from backend.agentloop.step_prompted import PromptedToolStep  # noqa: E402
```

> 实现说明：为避免 Task 3/4 同文件来回改，把 `PromptedToolStep` 放在同一 `step.py` 内更简单。本计划把它拆成 Task 4 在 `step.py` 内补类。**实现者：直接在 `step.py` 内先写一个最小 `PromptedToolStep`（仅 `__init__`+`format_observation`+`run` 抛 NotImplementedError）让 Task 3 测试通过，Task 4 再补全 `run`。** 删去上面那行 `from ... import` 占位，改为同文件定义。

修订：Task 3 在 `step.py` 内**同时定义** `NativeToolStep`、`build_step`、以及一个**最小 `PromptedToolStep`**（`run` 暂 `raise NotImplementedError`，`format_observation` 已按折叠 user 实现），使 `test_build_step_picks_prompted_for_glm` 通过（只断言类型，不调用 run）。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/agentloop/test_step.py -v` → PASS（5 passed）。

- [ ] **Step 5: Commit**

```bash
git add backend/agentloop/step.py tests/agentloop/test_step.py
git commit -m "feat(agentloop): NativeToolStep + build_step（provider 选 Native/Prompted）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: PromptedToolStep（提示式工具模拟）

**Files:** Modify `backend/agentloop/step.py`；Test `tests/agentloop/test_step_prompted.py`

**Interfaces:** `PromptedToolStep.run` 用 `client.chat`（无 tools），注入工具协议 system 前导，`BaseSkill.extract_json` 解析；产出 JSON 含 `tool` → 合成一个 `ToolCall(id=f"prompted-{n}", name, arguments)`；否则 `tool_calls=[]`（最终答案）。`format_observation` 折叠为 `{"role":"user","content": f"[工具 {call.name} 返回]\n{obs.to_tool_content()}"}`。`raw_assistant_msg = {"role":"assistant","content": 原始文本}`。

- [ ] **Step 1: 写失败测试**

Create `tests/agentloop/test_step_prompted.py`:
```python
from backend.agentloop.schemas import Observation, ToolCall
from backend.agentloop.step import PromptedToolStep


class _PlainClient:
    provider_id = "glm"

    def __init__(self, text):
        self._text = text

    async def chat(self, messages, *, max_tokens=None):
        return {"message": {"role": "assistant", "content": self._text, "thinking": ""}}


async def test_prompted_parses_tool_json():
    c = _PlainClient('{"tool":"get_command_usage","arguments":{"command_name":"give"}}')
    sr = await PromptedToolStep(c).run([{"role": "user", "content": "x"}], [])
    assert len(sr.tool_calls) == 1
    assert sr.tool_calls[0].name == "get_command_usage"
    assert sr.tool_calls[0].arguments == {"command_name": "give"}
    assert sr.tool_calls[0].id.startswith("prompted-")


async def test_prompted_final_answer_no_tool():
    c = _PlainClient('{"type":"single_command","command":{"command":"/say hi"}}')
    sr = await PromptedToolStep(c).run([{"role": "user", "content": "x"}], [])
    assert sr.tool_calls == []
    assert "single_command" in sr.content


def test_prompted_format_observation_folds_to_user():
    step = PromptedToolStep(_PlainClient(""))
    msg = step.format_observation(ToolCall("p-0", "search_wiki", {}), Observation("search_wiki", True, "命中"))
    assert msg["role"] == "user"
    assert "search_wiki" in msg["content"] and "命中" in msg["content"]
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/agentloop/test_step_prompted.py -v` → FAIL（`run` NotImplementedError 或缺实现）。

- [ ] **Step 3: 实现 `PromptedToolStep.run`**

在 `backend/agentloop/step.py` 把最小 `PromptedToolStep` 补全：
```python
class PromptedToolStep(LLMStep):
    """对 supports_tools=False 的 provider，用提示式 JSON 协议模拟工具调用。"""

    def __init__(self, client) -> None:
        self._client = client
        self._round = 0

    async def run(self, messages, tool_schemas) -> StepResult:
        from backend.skills.base import BaseSkill

        msgs = self._ensure_protocol(messages, tool_schemas)
        resp = await self._client.chat(msgs, max_tokens=AGENT_LOOP_MAX_TOKENS)
        msg = resp["message"]
        content = msg.get("content", "")
        thinking = msg.get("thinking", "")
        data = BaseSkill.extract_json(content)
        tool_calls: list[ToolCall] = []
        if isinstance(data, dict) and data.get("tool"):
            tool_calls = [ToolCall(
                id=f"prompted-{self._round}",
                name=str(data["tool"]),
                arguments=data.get("arguments", {}) if isinstance(data.get("arguments"), dict) else {},
            )]
            self._round += 1
        return StepResult(content=content, thinking=thinking, tool_calls=tool_calls,
                          raw_assistant_msg={"role": "assistant", "content": content})

    def _ensure_protocol(self, messages, tool_schemas) -> list[dict[str, Any]]:
        # 若首条 system 未含工具协议，则注入一次
        if messages and messages[0].get("role") == "system" and "__tools_injected__" in messages[0]:
            return messages
        manifest_lines = ["你可使用以下工具。若需调用，仅输出 JSON：{\"tool\":\"<名称>\",\"arguments\":{...}}；若已得最终答案，直接输出最终结果（不要包工具 JSON）。可用工具："]
        for s in tool_schemas:
            fn = s.get("function", {})
            manifest_lines.append(f"- {fn.get('name')}: {fn.get('description','')}")
        manifest = "\n".join(manifest_lines)
        new = list(messages)
        if new and new[0].get("role") == "system":
            new[0] = {**new[0], "content": new[0]["content"] + "\n\n" + manifest, "__tools_injected__": True}
        else:
            new.insert(0, {"role": "system", "content": manifest, "__tools_injected__": True})
        return new

    def format_observation(self, call: ToolCall, obs: Observation) -> dict[str, Any]:
        return {"role": "user", "content": f"[工具 {call.name} 返回]\n{obs.to_tool_content()}"}
```

> `__tools_injected__` 标记键会被 `_prep_messages` 透传给 provider 吗？不会进入 OpenAI 请求体的标准字段——但稳妥起见，实现者确认 `client.chat` 路径不会因多余键报错（DeepSeek/GLM 的 OpenAI 兼容接口忽略未知顶层键；若担心，改用实例属性记注入状态而非塞进 message dict）。**推荐**：用 `self._protocol_injected` 布尔实例属性记状态，避免污染 message。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/agentloop/test_step_prompted.py tests/agentloop/test_step.py -v` → PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/agentloop/step.py tests/agentloop/test_step_prompted.py
git commit -m "feat(agentloop): PromptedToolStep 提示式工具模拟（GLM 等无原生工具 provider）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: AgentLoop.run

**Files:** Create `backend/agentloop/loop.py`；Test `tests/agentloop/test_loop.py`

**Interfaces:** `AgentLoop(*, registry, step, budget, edition)`；`async run(messages) -> AsyncGenerator[dict]`：逐轮 yield `{"event":"thinking","data":{"text":...}}`；终止时 yield 内部事件 `{"event":"_agent_outcome","data":{"outcome": AgentOutcome}}` 并存 `self.last_outcome`。

**算法（镜像 task_agent.py:1006-1049 预算纪律）：**
1. `ctx = ToolContext(edition=self.edition, budget=self.budget, counters={})` —— **在 run() 内构造，每次全新**。
2. `for round_idx in range(budget.max_rounds)`：
   a. `sr = await step.run(messages, registry.get_schemas())`
   b. thinking 累积用 `"\n---\n"` 分隔；非空则 yield thinking 事件。
   c. **隐式完成**：`not sr.tool_calls` → IMPLICIT_DONE，content=sr.content，break。
   d. append `sr.raw_assistant_msg`。
   e. 逐 `ToolCall`：
      - `name=="finish"` → 跑 handler，读 `data["reason"]`/`data["final_answer"]`，映射 done/ask_user/give_up，content=final_answer，break 双层。
      - 否则 `obs = await registry.execute(call.name, call.arguments, ctx)`（registry 已保证不抛），append `step.format_observation(call, obs)`。
   f. **预算警告**：`round_idx+1 == budget.warn_at_round` 时 append `{"role":"user","content": budget.warning_text(round_idx+1)}`。
3. **预算耗尽**：循环未 finish → 一次 `step.run(messages, [])`（无工具）取最终内容，reason=BUDGET_EXHAUSTED。
4. 产出 `AgentOutcome(reason, content, thinking, observations, rounds_used)`。

- [ ] **Step 1: 写失败测试**

Create `tests/agentloop/test_loop.py`:
```python
from backend.agentloop.loop import AgentLoop
from backend.agentloop.schemas import (
    AgentOutcome, FinishReason, LoopBudget, Observation, StepResult, ToolCall,
)
from backend.agentloop.tools.registry import ToolRegistry


class _ScriptStep:
    """按脚本逐轮返回 StepResult。"""
    def __init__(self, script):
        self._script = script
        self.calls = 0

    async def run(self, messages, tool_schemas):
        sr = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        return sr

    def format_observation(self, call, obs):
        return {"role": "tool", "tool_call_id": call.id, "content": obs.to_tool_content()}


def _finish_registry(reason="done", answer="/give @p diamond"):
    reg = ToolRegistry()
    async def finish_handler(args, ctx):
        return Observation("finish", True, "finish", data={"reason": args.get("reason", reason), "final_answer": args.get("final_answer", answer)})
    reg.register({"type": "function", "function": {"name": "finish", "description": "d", "parameters": {"type": "object", "properties": {}}}}, finish_handler)
    return reg


async def _collect(loop, messages):
    events = []
    async for ev in loop.run(messages):
        events.append(ev)
    return events, loop.last_outcome


async def test_finish_done_round1():
    step = _ScriptStep([StepResult("", "", [ToolCall("c1", "finish", {"reason": "done", "final_answer": "/give @p diamond"})], {"role": "assistant", "content": ""})])
    loop = AgentLoop(registry=_finish_registry(), step=step, budget=LoopBudget(max_rounds=8), edition="bedrock")
    _, outcome = await _collect(loop, [{"role": "user", "content": "钻石"}])
    assert outcome.reason == FinishReason.DONE
    assert outcome.content == "/give @p diamond"
    assert outcome.rounds_used == 1


async def test_implicit_done():
    step = _ScriptStep([StepResult("最终答案", "", [], {"role": "assistant", "content": "最终答案"})])
    loop = AgentLoop(registry=ToolRegistry(), step=step, budget=LoopBudget(), edition="bedrock")
    _, outcome = await _collect(loop, [{"role": "user", "content": "x"}])
    assert outcome.reason == FinishReason.IMPLICIT_DONE
    assert outcome.content == "最终答案"


async def test_tool_error_becomes_observation_and_continues():
    reg = ToolRegistry()
    async def boom(args, ctx):
        raise RuntimeError("炸")
    reg.register({"type": "function", "function": {"name": "boom", "description": "d", "parameters": {"type": "object", "properties": {}}}}, boom)
    # 第一轮调 boom（出错→observation），第二轮隐式完成
    step = _ScriptStep([
        StepResult("", "", [ToolCall("c1", "boom", {})], {"role": "assistant", "content": ""}),
        StepResult("好了", "", [], {"role": "assistant", "content": "好了"}),
    ])
    loop = AgentLoop(registry=reg, step=step, budget=LoopBudget(), edition="bedrock")
    events, outcome = await _collect(loop, [{"role": "user", "content": "x"}])
    assert outcome.reason == FinishReason.IMPLICIT_DONE  # 未崩
    assert step.calls == 2


async def test_budget_exhaustion():
    # 每轮都调一个无害工具、从不 finish → 耗尽后一次无工具收尾
    reg = ToolRegistry()
    async def noop(args, ctx):
        return Observation("noop", True, "ok")
    reg.register({"type": "function", "function": {"name": "noop", "description": "d", "parameters": {"type": "object", "properties": {}}}}, noop)
    call = StepResult("", "", [ToolCall("c", "noop", {})], {"role": "assistant", "content": ""})
    final = StepResult("收尾", "", [], {"role": "assistant", "content": "收尾"})
    step = _ScriptStep([call] * 8 + [final])
    loop = AgentLoop(registry=reg, step=step, budget=LoopBudget(max_rounds=3, warn_at_round=2), edition="bedrock")
    _, outcome = await _collect(loop, [{"role": "user", "content": "x"}])
    assert outcome.reason == FinishReason.BUDGET_EXHAUSTED
    assert outcome.content == "收尾"


async def test_fresh_counters_per_run():
    # 同一 loop 实例跑两次，第二次 search_web 预算应重置（不泄漏）
    reg = ToolRegistry()
    seen = []
    async def sw(args, ctx):
        seen.append(ctx.counters.get("search_web", 0))
        ctx.counters["search_web"] = ctx.counters.get("search_web", 0) + 1
        return Observation("search_web", True, "ok")
    reg.register({"type": "function", "function": {"name": "search_web", "description": "d", "parameters": {"type": "object", "properties": {}}}}, sw)
    step1 = _ScriptStep([StepResult("", "", [ToolCall("c", "search_web", {})], {"role": "assistant", "content": ""}), StepResult("done", "", [], {"role": "assistant", "content": "done"})])
    loop = AgentLoop(registry=reg, step=step1, budget=LoopBudget(), edition="bedrock")
    await _collect(loop, [{"role": "user", "content": "1"}])
    loop._step = _ScriptStep([StepResult("", "", [ToolCall("c", "search_web", {})], {"role": "assistant", "content": ""}), StepResult("done", "", [], {"role": "assistant", "content": "done"})])
    await _collect(loop, [{"role": "user", "content": "2"}])
    assert seen == [0, 0]  # 两次都从 0 开始
```

> 注：`loop._step` 用于第二次注入新脚本——实现时 `AgentLoop` 把 step 存为 `self._step`。若命名不同，调整测试。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/agentloop/test_loop.py -v` → FAIL。

- [ ] **Step 3: 实现 `AgentLoop`**

Create `backend/agentloop/loop.py`（按上文算法；finish 检测在执行其它工具前；逐工具 `registry.execute`；预算耗尽再一次 `step.run(messages, [])`）。`run` 是 async generator：yield thinking 事件，结尾 yield `{"event":"_agent_outcome","data":{"outcome": outcome}}` 并 `self.last_outcome = outcome`。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/agentloop/test_loop.py -v` → PASS（5 passed）。

- [ ] **Step 5: Commit**

```bash
git add backend/agentloop/loop.py tests/agentloop/test_loop.py
git commit -m "feat(agentloop): AgentLoop.run（finish/隐式完成/工具错误观察/预算警告与耗尽/全新 counters）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: orchestrator 接线（单任务守卫 + _run_single_task_loop）

**Files:** Modify `backend/orchestrator/orchestrator.py`；Test `tests/agentloop/test_orchestrator_loop.py`

**做法（关键 — 防双执行）：** 先通读 `process_message_stream`。在 **`task_list` 事件发出之后、`TaskManager` 构造之前**（约 :524）插入单一守卫分支：
```python
if USE_AGENT_LOOP and is_single and len(tasks) == 1:
    async for event in self._run_single_task_loop(tasks[0], user_input, session_id, edition):
        yield event
    return
# 否则：原路径（L526 起）逐字不变
```
**绝不**改 :526 之后的旧单/多任务代码（用 `git diff` 自查）。

新方法 `_run_single_task_loop(self, task_def, user_input, session_id, edition)` 发出**逐字相同**的事件：
1. 发 `task_update`(generating)（复用 `task_agent._task_event` 或同形状）。
2. `messages = single_task.build_single_task_messages(user_request, output_type, build_command_directory_text(edition), edition=edition)`（`output_type` 取自 `task_def`，`user_request` 取自 task_def/`user_input`，与旧单任务取值一致）。
3. `loop = AgentLoop(registry=build_default_registry(), step=build_step(get_llm_client()), budget=LoopBudget(max_rounds=AGENT_LOOP_MAX_ROUNDS, warn_at_round=AGENT_LOOP_MAX_ROUNDS-1), edition=edition)`。
4. `async for ev in loop.run(messages)`：thinking → 转发为旧的 `task_thinking`/`thinking` 形状（与 task_agent.py:971-974 对齐）；捕获 `_agent_outcome`。
5. `_outcome_to_result(outcome, output_type)`：
   - ASK_USER → 构造 conversation 结果（与 task_agent.py:1095-1106 同形）→ 发 `task_update`(paused, result) → **return**（不校验）。
   - 其余（DONE/IMPLICIT_DONE/BUDGET_EXHAUSTED/GIVE_UP）→ `result = single_task.parse_output(outcome.content, output_type)`；挂 thinking。
6. 发 `task_update`(validating)；`single_task.run_validation(result)`。
7. 与旧单任务分支相同的后处理（orchestrator.py:552-559）：project → `_post_process_project`；single_command → `_structural_validate_and_retry_simple`。
8. `formatted = output_formatter.format_result(result)`；发 `{"event":"content","data":formatted}`；发 `{"event":"done","data":{}}`。

**暂停/resume = 重跑（re-run-fresh）：** 不把 loop 存进 `_active_sessions`。暂停只发 conversation + done。用户回复带旧 `task_id` 但无 active session → 走全新 decompose + 全新 loop；把用户答复并入 `user_input`（前端 questions 负载已回传原问题，可拼回上下文）。**实现者确认**：`USE_AGENT_LOOP` 且带 `task_id` 但无 active session 时，把原问题上下文并入 `user_input` 再 decompose。

- [ ] **Step 1: 写失败测试**

Create `tests/agentloop/test_orchestrator_loop.py`（用 mock 的 LLM client + monkeypatch `build_step` 返回脚本化 step，断言事件序列；并断言 flag off 时不走新路径）。最少断言：
```python
import backend.orchestrator.orchestrator as orch_mod


async def test_flag_off_does_not_use_loop(monkeypatch):
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", False)
    called = {"n": 0}
    # 若 _run_single_task_loop 被调用则失败
    ...
    # 走旧 TaskManager 路径（可对单任务 decomposition mock）；断言 called["n"] == 0


async def test_flag_on_single_task_done_event_order(monkeypatch):
    monkeypatch.setattr(orch_mod, "USE_AGENT_LOOP", True)
    # monkeypatch build_step → 脚本 step 直接 finish(done, <valid json>)
    # 收集 process_message_stream 事件，断言顺序：
    #   task_list → task_update(generating) → [task_thinking*] → task_update(validating) → content → done
    # 且 content.data 的 type == "single_command"
    ...


async def test_flag_on_ask_user_pauses(monkeypatch):
    # 脚本 step 直接 finish(ask_user, "你要钻石剑还是铁剑？")
    # 断言：task_update(paused) 含 conversation 结果，然后 done；无 validating/content
    ...
```
> 实现者：依 `process_message_stream` 的真实入参/mock 点补全这三个测试骨架（decomposition 注入、build_step monkeypatch、事件收集）。三条断言是验收门槛。

- [ ] **Step 2: 运行确认失败** → FAIL。

- [ ] **Step 3: 实现守卫 + `_run_single_task_loop` + `_outcome_to_result`**（按「做法」；import `USE_AGENT_LOOP/AGENT_LOOP_MAX_ROUNDS` from config，`AgentLoop/build_step/build_default_registry/LoopBudget/single_task` from agentloop）。

- [ ] **Step 4: 运行确认通过 + 全量回归**

Run: `.venv/bin/python -m pytest tests/ -q` → 全绿。
Run（多任务不变自查）: `git diff <task5_head>..HEAD -- backend/orchestrator/orchestrator.py` → 确认除守卫插入 + 新方法外，旧代码无改动。

- [ ] **Step 5: Commit**

```bash
git add backend/orchestrator/orchestrator.py tests/agentloop/test_orchestrator_loop.py
git commit -m "feat(agentloop): orchestrator 单任务接线（USE_AGENT_LOOP 守卫，多任务不变）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: 端到端 / 回归 / parity 汇总

**Files:** Create `tests/agentloop/test_e2e_loop.py`

**Interfaces:** 无新代码，纯测试。

- [ ] **Step 1: 写端到端测试**

Create `tests/agentloop/test_e2e_loop.py`，至少覆盖：
1. **flag-off 回归**：`USE_AGENT_LOOP=false` 下 `process_message_stream` 单/多任务，mock LLM，断言事件序列与捕获的 golden 一致（证明守卫插入在关时完全惰性）。
2. **flag-on happy path**：mock LLM `finish(done,<valid json>)` → 终 `content` 事件 `formatted` 的 `type=="single_command"`，validation 已并入，`output_formatter` 形状不变。
3. **prompted provider**：强制 `supports_tools=False` → 走 `PromptedToolStep`，折叠 `role:user` observation，仍达 DONE。
4. **chat.py 持久化不变**：循环路径终端用户事件是 `content`，确认 `_event_generator`（chat.py:122-123/132-147）按 `content` 收集 `collected_result` 不需改动。

- [ ] **Step 2: 运行确认（先红后绿，按需补实现）** → 全绿。

- [ ] **Step 3: 全量回归**

Run: `.venv/bin/python -m pytest tests/ -q` → 全绿（Phase 1 + 2A + 2B）。

- [ ] **Step 4: Commit**

```bash
git add tests/agentloop/test_e2e_loop.py
git commit -m "test(agentloop): 2B 端到端 — flag-off 回归 / flag-on happy / prompted / 持久化

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage（设计 spec 第 5.1 AgentLoop / 5.2 LLMStep / 5.9 build=循环 的单任务前置 / 决策④⑤）**
- AgentLoop（计划→行动→观察→校验→终止，错误转观察，显式终止）→ Task 5 ✓
- LLMStep 单一接口 + Native + Prompted 模拟（决策④）→ Tasks 3-4 ✓
- 显式终止动作 done/ask_user/give_up（决策⑤）→ finish 工具(2A) + loop 映射(Task 5) ✓
- 接 chat 单任务、多任务不动 → Task 6 ✓
- 开关默认关、可灰度 → Task 1/6 ✓
- 单任务 prompt/parse/validate 唯一实现（parity）→ Task 2 ✓

**2. Placeholder scan**：Task 6 的测试骨架标注「实现者补全三条验收断言」——非占位符，是明确的验收门槛 + 需依真实 mock 点补全；Task 2 的 parity 用 `TaskAgent.__new__` oracle 有「若读 self 状态则提参」的明确分支处理。其余均完整代码。

**3. Type consistency / 风险闭环**：
- `StepResult/ToolCall/Observation/AgentOutcome/LoopBudget/FinishReason` 复用 2A schemas，签名一致 ✓
- 双执行风险 → Task 6 守卫在 TaskManager 构造前 + git diff 自查 ✓
- prompted 工具消息分叉 → `format_observation` 双实现 + Task 4 断言 role 分歧 ✓
- 全新 counters → Task 5 `test_fresh_counters_per_run` ✓
- 解析 parity → Task 2 冻结语料 old-vs-new ✓
- edition 不对称 → Task 2 保留无 edition 校验 + 注释 ✓
- chat.py 不改 → Task 7 用例 4 确认 `content` 事件路径 ✓
