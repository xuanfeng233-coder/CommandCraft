# Phase 5 — 清理（删死 RAG + SSRF 硬化 + 文档）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构收尾的安全清理：删除已死的 RAG 子系统；硬化 `/api/settings/verify` 的 SSRF（与 Phase 1 模型发现同款）+ 补 url_guard 的 CGNAT 缺口；更新 CLAUDE.md 记录新架构/开关/SearXNG。**不删**任何 flag-off 仍依赖的代码（TaskAgent / MainAgent.decompose / build 五件套）——它们在开关默认开并经生产验证前必须保留。

**Architecture:** Phase 1-4 已落地 `backend/llm/`、`backend/agentloop/`、`backend/agents/planner*`，chat/build 双模式统一循环均在开关后（`USE_AGENT_LOOP` / `BUILD_USE_AGENT_LOOP` / `BUILD_LOOP_REVIEW`，全默认关）。`backend/rag/`（ChromaDB+bge-m3）自始未被任何 agent/endpoint 调用、且 import 即报错（Phase 1 审计确认），为纯死代码。

**Tech Stack:** Python 3.11；测试 pytest。

## Global Constraints

- 语言：注释/文档中文。
- **不删 flag-off 依赖**：TaskAgent、MainAgent（decompose/summarize）、`build/agents/{clarify,write,reader,review,search}`、`/api/settings` 既有端点、`/clarify` 端点——全部保留（开关默认关时是活路径）。删除仅限**确证无人引用**的 `backend/rag/`。
- **删前确证**：删 `backend/rag/` 前 grep 全仓确认无 live importer（仅 rag/ 内部互引不算）；删后全量测试绿。
- **安全硬化向后兼容**：`/verify` 加 SSRF 校验——合法 provider 的公网 https 仍通过；仅拦内网/环回/CGNAT/元数据。url_guard 改动默认行为不变（现有调用方与测试不破）。
- **prompt 抽取本期不做**（触 flag-off 关键的 main_agent prompt，风险高、纯重构）——记入「后续」。
- 提交频繁，提交信息中文 + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。测试 `.venv/bin/python -m pytest`，pristine。

---

## File Structure

**删除**
- `backend/rag/`（`__init__.py` / `embedder.py` / `indexer.py` / `retriever.py` / `vector_store.py`）
- 任何只服务 RAG 的 `scripts/*`（删前确认）；`requirements.txt` 里仅 RAG 用的依赖（chromadb / sentence-transformers，若在且无他用）

**修改**
- `backend/llm/url_guard.py` — `_is_blocked_ip` 增 `not ip.is_global`（拦 CGNAT 100.64/10 等非全局段）
- `backend/api/settings.py` — `/verify` 端点对 `base_url` 做 `assert_safe_outbound_url` 预校验
- `tests/llm/test_url_guard.py` — 补 CGNAT 用例
- `CLAUDE.md` — 新架构/开关/SearXNG/模型目录/repo 修复/后续删除清单

**新建**
- `tests/api/test_settings_verify_ssrf.py`

---

## Task 1: 删除死 RAG 子系统

**Files:** Delete `backend/rag/`；可能修改 `requirements.txt`、删 RAG 专用 `scripts/*`

- [ ] **Step 1: 删前确证无引用**

Run（必须为空才可删）:
```bash
grep -rn "backend.rag\|backend\.rag\|from backend import rag" backend/ tests/ scripts/ --include="*.py" | grep -v "backend/rag/"
```
Expected: 空输出。若有引用 → STOP，报告引用点（不可删）。

同时确认 main.py / lifespan / api 不引 rag：
```bash
grep -rn "chromadb\|sentence_transformers\|vector_store\|indexer\|embedder\|retriever" backend/ --include="*.py" | grep -v "backend/rag/" | grep -vi "embedding_client"
```
（`backend/utils/embedding_client.py` 是订阅嵌入客户端，**与 rag 无关**，勿删——确认它不 import backend.rag。）

- [ ] **Step 2: 删除 rag 包**

```bash
git rm -r backend/rag/
```

- [ ] **Step 3: 清理 RAG 专用依赖/脚本（确认后）**

查 `requirements.txt` 是否有 `chromadb` / `sentence-transformers` 且全仓再无引用（除已删的 rag/）：
```bash
grep -niE "chromadb|sentence-transformers|sentence_transformers" requirements.txt backend/requirements.txt 2>/dev/null
grep -rniE "chromadb|sentence_transformers" backend/ --include="*.py"
```
若依赖仅 RAG 用 → 从 requirements 删除；否则保留。查 `scripts/` 下 RAG 建索引脚本（如 `build_index`/`index_*`），仅服务 RAG 且 import backend.rag 的可一并 `git rm`（先 grep 确认）。**有疑问就保留并在报告说明**。

- [ ] **Step 4: 全量回归**

Run: `.venv/bin/python -m pytest tests/ -q` → 全绿（179 passed，删 rag 不应影响任何测试，因其本就无人调用）。
Run: `.venv/bin/python -c "import backend.main"` → 无 ImportError（确认 lifespan 不引 rag）。

- [ ] **Step 5: Commit**
```bash
git add -A
git commit -m "chore(cleanup): 删除已死的 RAG 子系统（ChromaDB+bge-m3，自始无人调用、import 即报错）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: SSRF 硬化（/verify + url_guard CGNAT）

**Files:** Modify `backend/llm/url_guard.py`, `backend/api/settings.py`；Modify `tests/llm/test_url_guard.py`；Create `tests/api/test_settings_verify_ssrf.py`

**背景：** `/api/settings/verify`（`settings.py` 约 :70）从请求体取 `base_url`，`set_config` 后立即 `llm_client.check_health()` 向该 `base_url` 发服务端请求——与 Phase 1 已修的模型发现同款 SSRF（后端经 Cloudflare 暴露公网、同机有 loopback 内部服务）。url_guard 还漏了 CGNAT `100.64.0.0/10`（Phase 2A 审阅指出）。

- [ ] **Step 1: url_guard CGNAT — 先测试**

在 `tests/llm/test_url_guard.py` 追加：
```python
def test_rejects_cgnat_shared_address():
    # CGNAT 100.64.0.0/10（共享地址段）非全局，应拒
    with pytest.raises(UnsafeURLError):
        assert_safe_outbound_url("http://x/m", resolver=_resolver("100.64.0.1"))


def test_allows_public_still_passes():
    # 回归：公网 IP 仍通过
    assert_safe_outbound_url("https://api/v1/models", resolver=_resolver("93.184.216.34"))
```
Run `.venv/bin/python -m pytest tests/llm/test_url_guard.py -k "cgnat or public_still" -v` → CGNAT 用例 FAIL（当前未拦）。

- [ ] **Step 2: url_guard 实现**

`backend/llm/url_guard.py` `_is_blocked_ip` 的 OR 链增加 `not ip.is_global`（在 allow_loopback 的环回豁免**之后**，保证 allow_loopback 仍只豁免环回）：
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
        or not ip.is_global   # CGNAT(100.64/10) 等非全局段一并拦截
    )
```
Run `.venv/bin/python -m pytest tests/llm/test_url_guard.py -v` → 全绿（含既有 allow_loopback：环回在 allow_loopback=True 时仍豁免，因 `not is_global` 在豁免之后才判，且豁免直接 return False）。
> 注意：确认既有用例 `test_allow_loopback_permits_127` 仍过——`127.0.0.1` 在 `allow_loopback=True` 时第一分支 `return False`，不会走到 `not is_global`。✅

- [ ] **Step 3: /verify SSRF — 先测试**

Create `tests/api/test_settings_verify_ssrf.py`（最小 FastAPI app 含 settings router，monkeypatch `backend.llm.url_guard._resolve_host` 与 `llm_client.check_health`）:
```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.settings as settings_module


def _client():
    app = FastAPI()
    app.include_router(settings_module.router)
    return TestClient(app)


def test_verify_rejects_internal_base_url(monkeypatch):
    # base_url 解析到内网 → 预校验拒，不真正发健康检查
    monkeypatch.setattr("backend.llm.url_guard._resolve_host", lambda host, port: ["127.0.0.1"])
    called = {"n": 0}

    async def _health():
        called["n"] += 1
        return True, True

    from backend.utils.llm_client import llm_client
    monkeypatch.setattr(llm_client, "check_health", _health)

    resp = _client().post("/api/settings/verify", json={
        "provider_id": "custom", "api_key": "k", "base_url": "http://127.0.0.1:8003/v1", "model": "m",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "受限" in body["error"] or "地址" in body["error"]
    assert called["n"] == 0  # 健康检查未被调用（SSRF 在发起前被拦）


def test_verify_allows_public_base_url(monkeypatch):
    monkeypatch.setattr("backend.llm.url_guard._resolve_host", lambda host, port: ["93.184.216.34"])

    async def _health():
        return True, True

    from backend.utils.llm_client import llm_client
    monkeypatch.setattr(llm_client, "check_health", _health)

    resp = _client().post("/api/settings/verify", json={
        "provider_id": "deepseek", "api_key": "k", "base_url": "https://api.deepseek.com", "model": "deepseek-chat",
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
```
Run → `test_verify_rejects_internal_base_url` FAIL（当前无校验）。

- [ ] **Step 4: /verify 实现**

`backend/api/settings.py` `verify_config`：在 `set_config` / `check_health` **之前**，对解析后的 `base_url` 做 `assert_safe_outbound_url`（base_url 为空时用 provider 默认，与 `/models` 端点一致）。捕获 `UnsafeURLError` → 返回 `VerifyResponse(ok=False, error="base_url 指向受限地址，已拒绝")`：
```python
from backend.llm.url_guard import UnsafeURLError, assert_safe_outbound_url
from backend.utils.providers import get_provider

@router.post("/verify", response_model=VerifyResponse)
async def verify_config(req: LLMSettingsRequest):
    base_url = req.base_url or (get_provider(req.provider_id).base_url if get_provider(req.provider_id) else "")
    if base_url:
        try:
            assert_safe_outbound_url(base_url)
        except UnsafeURLError:
            return VerifyResponse(ok=False, error="base_url 指向受限地址，已拒绝")
    # ... 原有 set_config + check_health 逻辑不变
```
（不改 `/config`/`/models`——`/models` 已在 Phase 1 经 ModelCatalog 内部 url_guard；`/config` 不发外呼。）

- [ ] **Step 5: 运行确认通过 + 全量回归**

Run: `.venv/bin/python -m pytest tests/api/test_settings_verify_ssrf.py tests/llm/test_url_guard.py -v` → PASS。
Run: `.venv/bin/python -m pytest tests/ -q` → 全绿。

- [ ] **Step 6: Commit**
```bash
git add backend/llm/url_guard.py backend/api/settings.py tests/llm/test_url_guard.py tests/api/test_settings_verify_ssrf.py
git commit -m "fix(security): /verify 加 SSRF 校验 + url_guard 拦 CGNAT（非全局段）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: 更新 CLAUDE.md（新架构 / 开关 / SearXNG / 后续）

**Files:** Modify `CLAUDE.md`

- [ ] **Step 1: 改 CLAUDE.md**

新增/更新以下内容（保持其余不变）：
1. **Agent 架构（重写）**：双模式（chat/build）现可走统一 Agent 循环 `backend/agentloop/`（`AgentLoop` + `ToolRegistry` 7 工具 + `LLMStep` Native/Prompted + `single_task` 助手）；`backend/agents/planner.py` typed Planner（Decomposition 校验/修复，取消静默降级）；orchestrator 的 `TaskManager(use_loop=True)` 路由到 `_run_via_agentloop`。**全部藏在开关后，默认走旧路径**。
2. **特性开关**（新增小节）：`USE_AGENT_LOOP`（chat 单/多任务走统一循环，默认 false）、`BUILD_USE_AGENT_LOOP`（build 走 Planner+循环，默认 false）、`BUILD_LOOP_REVIEW`（build 完整性复查子开关，默认 false）。灰度：staging 用 env 翻开 → 看 SSE/质量 → 再默认开。翻开 chat 前确认前端渲染 `event:error`（已就绪）；翻开 build 前建议先开 `BUILD_LOOP_REVIEW`。
3. **LLM 管线**（更新）：`backend/llm/` 韧性客户端（重试/超时/分类异常）+ `ModelCatalog` 动态模型发现（`GET /v1/models` + curated 兜底，`POST /api/settings/models`）。`backend/utils/providers.py` 的 `models` 现为 curated 兜底。
4. **SearXNG 联网搜索**（新增）：`search_web` 工具经 `backend/agentloop/searxng_client.py`，本地优先、best-effort 软依赖。配置 `SEARXNG_URL`（默认空=禁用，建议本地 `http://127.0.0.1:8888`）/`SEARXNG_TIMEOUT`/`WEB_SEARCH_MAX_RESULTS`。部署：SearXNG 作独立 PM2 进程（loopback），挂了仅降级不阻塞。url_guard 对其 base_url 用 `allow_loopback=True`（仅运营方配置可达环回）。
5. **SSRF 防护**（新增）：`backend/llm/url_guard.py` 校验出站 URL（scheme + 解析后拦 内网/环回/链路本地/保留/组播/CGNAT）；`/api/settings/models` 与 `/verify` 及 SearXNG 客户端均经它。
6. **repo 修复**：`.gitignore` 的 `build/` 曾误伤 `backend/build/`（整 build 模块从未入库），已改 `/build/` 并补入源码。
7. **死 RAG 已删**：`backend/rag/`（ChromaDB+bge-m3）已删除（自始无人调用）。把 CLAUDE.md 里「RAG系统: ChromaDB 4个集合」「sentence-transformers 本地嵌入」「RAG 索引在应用启动时自动构建」等过时描述更新为现状（命令查询经 agentloop 工具 + 本地知识库；联网经 SearXNG）。
8. **后续（开关默认开后再做）**：删除 `TaskAgent`/`MainAgent.decompose,summarize`/`build/agents/{clarify,write,review,search}` 与 `/clarify` 端点 + 前端 clarify UI（flag-off 路径，现仍保留）；抽取 4 大 prompt 为模板（Bedrock/Java 共享 schema）。

- [ ] **Step 2: 提交**
```bash
git add CLAUDE.md
git commit -m "docs(claude): 更新 CLAUDE.md — 统一循环/开关/Planner/SearXNG/url_guard/删 RAG/后续清单

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage（设计 spec 第 9 期第 5 项 + 安全 follow-up）**
- 删死 RAG → Task 1 ✓
- `/verify` SSRF + CGNAT 硬化（Phase1/2A follow-up）→ Task 2 ✓
- CLAUDE.md 更新（SearXNG 部署 + 新架构 + 开关）→ Task 3 ✓
- 删降级路径重复 / 删旧 agent 家族 / 抽 prompt → **显式延后**到开关默认开后（flag-off 仍依赖），记入 CLAUDE.md 后续 ✓

**2. Placeholder scan**：Task 1 的依赖/脚本删除以「grep 确认后再删，有疑问保留」约束，非占位符。Task 3 内容清单具体。

**3. 风险闭环**：
- 删 RAG 前 grep 确证无引用 + 删后 import backend.main 无错 + 全量绿 → Task 1 Step1/4 ✓
- url_guard `not is_global` 加在 allow_loopback 豁免之后，既有 SearXNG 环回豁免不破 → Task 2 Step2 + 回归 ✓
- `/verify` 校验向后兼容（公网 https 通过，仅拦内网）→ Task 2 测试两面 ✓
- 不删 flag-off 依赖（全局约束）→ 仅删确证死的 rag/ ✓
