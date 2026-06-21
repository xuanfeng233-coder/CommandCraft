# Phase 1 — LLM 地基（韧性 + 动态模型发现）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 LLM 调用加上韧性（重试/超时/错误分类），并把写死的过时模型列表改成「运行时动态发现 + curated 静态兜底」，前端下拉始终最新。

**Architecture:** 新增 `backend/llm/` 包承载三块独立可测的地基：`errors.py`（异常分类）、`retry.py`（异步指数退避）、`catalog.py`（`ModelCatalog` 动态拉取 `/v1/models` + TTL 缓存 + curated 兜底）+ `curated_models.py`（新版兜底列表）。现有 `backend/utils/llm_client.py` 的三个 API 调用点被薄封装接入重试与超时；`backend/api/settings.py` 新增 `POST /api/settings/models` 端点暴露动态列表。这是整份 Agent 重构设计（`docs/superpowers/specs/2026-06-21-agent-redesign-design.md`）第 9 节的第 1 期，独立可上线。

**Tech Stack:** Python 3.11、FastAPI、OpenAI SDK（async）、httpx；测试用 pytest + pytest-asyncio + respx（本期新引入，none 现存）。

## Global Constraints

- 语言：所有面向用户的字符串、注释、文档为中文（项目惯例）。
- 异步优先：所有 IO 用 `async`/`await`（FastAPI + httpx）。
- 零静默降级：传输失败与「模型/数据非法」必须可区分；动态发现失败时回落 curated 必须返回 `source="curated"` 标记，且记 `logger.warning`。
- 不改运行时行为契约：`llm_client.chat/chat_stream/chat_with_tools` 的返回结构（Ollama 兼容 `{"message": {...}}` / 流式 chunk）保持不变——只在内部加韧性。
- 不新增重依赖：仅运行时复用已存在的 `httpx`/`openai`；测试依赖单独放 `backend/requirements-dev.txt`。
- 配置走环境变量 + `backend/config.py`，带默认值（与现有风格一致）。
- 提交频繁：每个 Task 末尾 commit；提交信息中文，结尾附带：
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

## File Structure

**新建（运行时）**
- `backend/llm/__init__.py` — 空包标记。
- `backend/llm/errors.py` — `LLMError`/`TransientLLMError`/`PermanentLLMError` + `classify_exception()`。
- `backend/llm/retry.py` — `with_retry()` 异步指数退避。
- `backend/llm/curated_models.py` — 各 provider 的新版 curated 兜底模型列表 + `curated_models_for()`。
- `backend/llm/catalog.py` — `ModelInfo` + `ModelCatalog`（动态发现 + TTL 缓存 + 兜底）+ `model_catalog` 单例。

**修改**
- `backend/config.py` — 新增 `LLM_REQUEST_TIMEOUT` / `LLM_MAX_RETRIES` / `LLM_RETRY_BASE_DELAY` / `MODEL_CATALOG_TTL`。
- `backend/utils/llm_client.py` — `configure()` 设 `max_retries=0` + `timeout`；新增 `_create()` 薄封装；三调用点改走 `_create()`。
- `backend/utils/providers.py` — `ProviderInfo.models` 改用 `curated_models_for()` 的新版列表（去掉过时模型）。
- `backend/api/settings.py` — 新增 `POST /api/settings/models`。

**新建（测试基建）**
- `backend/requirements-dev.txt` — pytest / pytest-asyncio / respx。
- `pytest.ini` — 仓库根，`pythonpath=.`、`asyncio_mode=auto`、`testpaths=tests`。
- `tests/__init__.py`、`tests/llm/__init__.py`。
- `tests/test_smoke.py`、`tests/llm/test_errors.py`、`tests/llm/test_retry.py`、`tests/llm/test_curated_models.py`、`tests/llm/test_catalog.py`、`tests/llm/test_llm_client_resilience.py`、`tests/llm/test_settings_models_api.py`。

---

## Task 1: 测试基建（pytest + asyncio + respx）

**Files:**
- Create: `backend/requirements-dev.txt`
- Create: `pytest.ini`
- Create: `tests/__init__.py`, `tests/llm/__init__.py`
- Create: `tests/test_smoke.py`

**Interfaces:**
- Consumes: 无。
- Produces: 一个可运行的 pytest 环境（`asyncio_mode=auto`，`async def test_*` 无需装饰器；仓库根在 `sys.path`，可 `import backend.*`）。

- [ ] **Step 1: 写测试依赖清单**

Create `backend/requirements-dev.txt`:
```text
pytest>=8.0.0
pytest-asyncio>=0.24.0
respx>=0.21.0
```

- [ ] **Step 2: 安装测试依赖**

Run: `.venv/bin/pip install -r backend/requirements-dev.txt`
Expected: 安装成功，末行类似 `Successfully installed pytest-8.x pytest-asyncio-0.2x respx-0.2x ...`（若已满足则 `Requirement already satisfied`）。

- [ ] **Step 3: 写 pytest 配置**

Create `pytest.ini`（仓库根）:
```ini
[pytest]
pythonpath = .
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
addopts = -q
```

- [ ] **Step 4: 写包标记与冒烟测试**

Create `tests/__init__.py`（空文件）。
Create `tests/llm/__init__.py`（空文件）。
Create `tests/test_smoke.py`:
```python
"""冒烟测试：验证 pytest 环境与 backend 包可导入。"""


def test_harness_runs():
    assert True


async def test_async_harness_runs():
    # asyncio_mode=auto：无需 @pytest.mark.asyncio
    assert True


def test_backend_importable():
    import backend.config as config

    assert hasattr(config, "MODEL_TEMPERATURE")
```

- [ ] **Step 5: 运行冒烟测试**

Run: `.venv/bin/python -m pytest tests/test_smoke.py -v`
Expected: PASS（3 passed），其中 `test_async_harness_runs` 不报「async def not natively supported」。

- [ ] **Step 6: Commit**

```bash
git add backend/requirements-dev.txt pytest.ini tests/__init__.py tests/llm/__init__.py tests/test_smoke.py
git commit -m "test: 引入 pytest+asyncio+respx 测试基建与冒烟用例

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: LLM 异常分类（`backend/llm/errors.py`）

**Files:**
- Create: `backend/llm/__init__.py`（空文件）
- Create: `backend/llm/errors.py`
- Test: `tests/llm/test_errors.py`

**Interfaces:**
- Consumes: 无。
- Produces:
  - `class LLMError(Exception)`；`class TransientLLMError(LLMError)`；`class PermanentLLMError(LLMError)`。
  - `def classify_exception(exc: BaseException) -> LLMError`：把任意异常映射成 `TransientLLMError`（可重试：连接/超时/429/5xx）或 `PermanentLLMError`（不可重试：鉴权/请求非法/4xx/未知）。返回的实例 `__cause__` 链到原始 `exc`，且 `str()` 保留原始信息。

- [ ] **Step 1: 写失败测试**

Create `tests/llm/test_errors.py`:
```python
import httpx
import pytest
from openai import APIStatusError, APITimeoutError

from backend.llm.errors import (
    LLMError,
    PermanentLLMError,
    TransientLLMError,
    classify_exception,
)


def _status_error(code: int) -> APIStatusError:
    request = httpx.Request("POST", "https://api.test.local/v1/chat/completions")
    response = httpx.Response(code, request=request)
    return APIStatusError("boom", response=response, body=None)


def test_httpx_timeout_is_transient():
    err = classify_exception(httpx.ReadTimeout("slow"))
    assert isinstance(err, TransientLLMError)


def test_httpx_connect_is_transient():
    err = classify_exception(httpx.ConnectError("refused"))
    assert isinstance(err, TransientLLMError)


def test_openai_timeout_is_transient():
    err = classify_exception(APITimeoutError(request=httpx.Request("POST", "https://x")))
    assert isinstance(err, TransientLLMError)


def test_http_429_is_transient():
    assert isinstance(classify_exception(_status_error(429)), TransientLLMError)


def test_http_503_is_transient():
    assert isinstance(classify_exception(_status_error(503)), TransientLLMError)


def test_http_401_is_permanent():
    assert isinstance(classify_exception(_status_error(401)), PermanentLLMError)


def test_http_400_is_permanent():
    assert isinstance(classify_exception(_status_error(400)), PermanentLLMError)


def test_unknown_is_permanent():
    assert isinstance(classify_exception(ValueError("nope")), PermanentLLMError)


def test_already_classified_passthrough():
    original = TransientLLMError("x")
    assert classify_exception(original) is original


def test_preserves_cause_and_message():
    src = httpx.ConnectError("refused")
    err = classify_exception(src)
    assert err.__cause__ is src
    assert "refused" in str(err)
    assert isinstance(err, LLMError)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/llm/test_errors.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'backend.llm.errors'`）。

- [ ] **Step 3: 实现**

Create `backend/llm/__init__.py`（空文件）。
Create `backend/llm/errors.py`:
```python
"""LLM 调用异常分类。

把底层 httpx / openai 异常映射为可重试(Transient)或不可重试(Permanent)，
让重试层据此决策。区分「传输失败」与「请求本身非法」，避免对永久错误盲目重试。
"""

from __future__ import annotations

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError


class LLMError(Exception):
    """LLM 调用错误基类。"""


class TransientLLMError(LLMError):
    """瞬时错误，可重试（连接/超时/429/5xx）。"""


class PermanentLLMError(LLMError):
    """永久错误，不可重试（鉴权/请求非法/4xx/未知）。"""


def _wrap(cls: type[LLMError], exc: BaseException) -> LLMError:
    err = cls(str(exc) or exc.__class__.__name__)
    err.__cause__ = exc
    return err


def classify_exception(exc: BaseException) -> LLMError:
    """把任意异常分类为 Transient / Permanent 的 LLMError。"""
    # 已分类：原样返回
    if isinstance(exc, LLMError):
        return exc

    # 传输层：连接/超时 → 瞬时
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return _wrap(TransientLLMError, exc)
    if isinstance(exc, (APITimeoutError, APIConnectionError)):
        return _wrap(TransientLLMError, exc)

    # HTTP 状态：429 或 5xx → 瞬时；其余 4xx → 永久
    if isinstance(exc, APIStatusError):
        code = getattr(exc, "status_code", None)
        if code == 429 or (isinstance(code, int) and code >= 500):
            return _wrap(TransientLLMError, exc)
        return _wrap(PermanentLLMError, exc)

    # 未知：保守按永久（避免对真实 bug 反复重试）
    return _wrap(PermanentLLMError, exc)
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/llm/test_errors.py -v`
Expected: PASS（10 passed）。

- [ ] **Step 5: Commit**

```bash
git add backend/llm/__init__.py backend/llm/errors.py tests/llm/test_errors.py
git commit -m "feat(llm): 新增异常分类 classify_exception（瞬时/永久）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: 异步指数退避重试（`backend/llm/retry.py`）

**Files:**
- Create: `backend/llm/retry.py`
- Test: `tests/llm/test_retry.py`

**Interfaces:**
- Consumes: `backend.llm.errors.classify_exception`、`PermanentLLMError`。
- Produces:
  - `async def with_retry(fn, *, max_attempts=3, base_delay=0.5, max_delay=8.0, sleep=asyncio.sleep)`：
    - `fn` 是无参 async 可调用；成功则返回其结果。
    - 异常经 `classify_exception` 分类；`PermanentLLMError` 或达到 `max_attempts` 立即抛出（抛出的是分类后的 `LLMError`）。
    - 瞬时错误重试，第 n 次重试前 `await sleep(min(max_delay, base_delay * 2**(n-1)))`（n 从 1 起，确定性、无 jitter）。
    - `sleep` 可注入，便于测试零等待。

- [ ] **Step 1: 写失败测试**

Create `tests/llm/test_retry.py`:
```python
import httpx
import pytest

from backend.llm.errors import PermanentLLMError, TransientLLMError
from backend.llm.retry import with_retry


def _recording_sleep():
    calls: list[float] = []

    async def sleep(d: float):
        calls.append(d)

    return calls, sleep


async def test_succeeds_first_try():
    async def fn():
        return "ok"

    assert await with_retry(fn, sleep=(await _noop_sleep())) == "ok"


async def _noop_sleep():
    async def sleep(_d):
        return None

    return sleep


async def test_retries_then_succeeds():
    attempts = {"n": 0}

    async def fn():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise httpx.ConnectError("refused")
        return "ok"

    calls, sleep = _recording_sleep()
    result = await with_retry(fn, max_attempts=3, base_delay=0.5, sleep=sleep)
    assert result == "ok"
    assert attempts["n"] == 3
    # 两次重试前各 sleep 一次：0.5, 1.0（确定性指数退避）
    assert calls == [0.5, 1.0]


async def test_permanent_raises_immediately():
    attempts = {"n": 0}

    async def fn():
        attempts["n"] += 1
        raise ValueError("bad request")  # 未知 → 永久

    calls, sleep = _recording_sleep()
    with pytest.raises(PermanentLLMError):
        await with_retry(fn, max_attempts=3, sleep=sleep)
    assert attempts["n"] == 1
    assert calls == []


async def test_transient_exhausts_and_raises():
    attempts = {"n": 0}

    async def fn():
        attempts["n"] += 1
        raise httpx.ReadTimeout("slow")

    calls, sleep = _recording_sleep()
    with pytest.raises(TransientLLMError):
        await with_retry(fn, max_attempts=3, base_delay=0.5, sleep=sleep)
    assert attempts["n"] == 3
    # 最后一次失败不再 sleep
    assert calls == [0.5, 1.0]


async def test_max_delay_caps_backoff():
    async def fn():
        raise httpx.ConnectError("refused")

    calls, sleep = _recording_sleep()
    with pytest.raises(TransientLLMError):
        await with_retry(fn, max_attempts=5, base_delay=1.0, max_delay=2.0, sleep=sleep)
    # 1, 2, 2, 2（被 max_delay=2.0 截断），第 5 次失败不 sleep
    assert calls == [1.0, 2.0, 2.0, 2.0]
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/llm/test_retry.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'backend.llm.retry'`）。

- [ ] **Step 3: 实现**

Create `backend/llm/retry.py`:
```python
"""异步指数退避重试。

仅对瞬时错误重试；永久错误立即抛出。退避确定性（无 jitter），
sleep 可注入便于测试零等待。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

from backend.llm.errors import PermanentLLMError, classify_exception

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """运行 fn()，对瞬时错误指数退避重试。

    成功返回结果；永久错误或重试耗尽抛出分类后的 LLMError。
    """
    attempt = 0
    while True:
        try:
            return await fn()
        except BaseException as exc:  # noqa: BLE001 - 统一分类后再决策
            err = classify_exception(exc)
            attempt += 1
            if isinstance(err, PermanentLLMError) or attempt >= max_attempts:
                raise err
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            logger.warning(
                "LLM 调用瞬时失败（第 %d/%d 次），%.1fs 后重试：%s",
                attempt, max_attempts, delay, err,
            )
            await sleep(delay)
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/llm/test_retry.py -v`
Expected: PASS（5 passed）。

- [ ] **Step 5: Commit**

```bash
git add backend/llm/retry.py tests/llm/test_retry.py
git commit -m "feat(llm): 新增 with_retry 异步指数退避（仅重试瞬时错误）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: 把韧性接入 LLMClient（`backend/utils/llm_client.py`）

**Files:**
- Modify: `backend/config.py`（新增超时/重试配置）
- Modify: `backend/utils/llm_client.py:102-125`（`configure`）、新增 `_create()`、改三调用点（`:166`、`:220`、`:307`）
- Test: `tests/llm/test_llm_client_resilience.py`

**Interfaces:**
- Consumes: `backend.llm.retry.with_retry`；`backend.config.LLM_REQUEST_TIMEOUT/LLM_MAX_RETRIES/LLM_RETRY_BASE_DELAY`。
- Produces: `LLMClient._create(**kwargs)` 内部方法（经 `with_retry` 调 `self._client.chat.completions.create`）。`chat/chat_stream/chat_with_tools` 行为契约不变，但瞬时错误自动重试、永久错误抛 `PermanentLLMError`。

- [ ] **Step 1: 加配置项**

Modify `backend/config.py` — 在 `MAX_PARALLEL_TASKS` 那一组附近新增：
```python
# LLM 韧性
LLM_REQUEST_TIMEOUT = float(os.environ.get("LLM_REQUEST_TIMEOUT", "60"))
LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "3"))
LLM_RETRY_BASE_DELAY = float(os.environ.get("LLM_RETRY_BASE_DELAY", "0.5"))
```

- [ ] **Step 2: 写失败测试**

Create `tests/llm/test_llm_client_resilience.py`:
```python
import types

import httpx
import pytest

from backend.llm.errors import PermanentLLMError
from backend.utils.llm_client import LLMClient


def _fake_response(content: str):
    message = types.SimpleNamespace(content=content, tool_calls=None)
    choice = types.SimpleNamespace(message=message)
    return types.SimpleNamespace(choices=[choice])


class _FakeCompletions:
    """按脚本逐次返回结果或抛异常。"""

    def __init__(self, script: list):
        self._script = script
        self.calls = 0

    async def create(self, **kwargs):
        item = self._script[self.calls]
        self.calls += 1
        if isinstance(item, BaseException):
            raise item
        return item


def _install_fake(client: LLMClient, script: list) -> _FakeCompletions:
    fake = _FakeCompletions(script)
    client._client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=fake)
    )
    client._model = "test-model"
    client._provider_id = "test"
    client._thinking_field = ""
    return fake


@pytest.fixture(autouse=True)
def _instant_sleep(monkeypatch):
    async def _no_sleep(_d):
        return None

    monkeypatch.setattr("backend.llm.retry.asyncio.sleep", _no_sleep)


async def test_chat_retries_transient_then_succeeds():
    client = LLMClient()
    fake = _install_fake(
        client,
        [httpx.ConnectError("refused"), _fake_response("hello")],
    )
    out = await client.chat([{"role": "user", "content": "hi"}])
    assert out["message"]["content"] == "hello"
    assert fake.calls == 2


async def test_chat_raises_permanent_immediately():
    client = LLMClient()
    fake = _install_fake(client, [ValueError("bad")])
    with pytest.raises(PermanentLLMError):
        await client.chat([{"role": "user", "content": "hi"}])
    assert fake.calls == 1
```

- [ ] **Step 3: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/llm/test_llm_client_resilience.py -v`
Expected: FAIL —— 当前 `chat` 直接调 `self._client.chat.completions.create`，瞬时错误不重试，`test_chat_retries_transient_then_succeeds` 会因 `httpx.ConnectError` 冒出而失败。

- [ ] **Step 4: 实现 —— 改 configure 与新增 _create**

Modify `backend/utils/llm_client.py`：
顶部 import（第 17 行）改为：
```python
from backend.config import MODEL_TEMPERATURE, LLM_REQUEST_TIMEOUT, LLM_MAX_RETRIES, LLM_RETRY_BASE_DELAY
```
`configure()` 里创建 `AsyncOpenAI` 处（第 113-118 行）改为：
```python
        # BUG-8 fix: bypass Windows system proxy
        http_client = httpx.AsyncClient(trust_env=False)
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            http_client=http_client,
            max_retries=0,            # 关闭 SDK 内置重试，统一由 _create 接管
            timeout=LLM_REQUEST_TIMEOUT,
        )
```
在 `chat()` 方法定义之前（第 139 行 `# -- Chat (non-streaming)` 注释上方）新增内部方法：
```python
    # -- Internal: resilient create ------------------------------------------

    async def _create(self, **kwargs: Any):
        """经指数退避重试调用底层 completions.create。

        瞬时错误（连接/超时/429/5xx）自动重试；永久错误抛 PermanentLLMError。
        """
        from backend.llm.retry import with_retry

        async def _call():
            return await self._client.chat.completions.create(**kwargs)

        return await with_retry(
            _call,
            max_attempts=LLM_MAX_RETRIES,
            base_delay=LLM_RETRY_BASE_DELAY,
        )
```

- [ ] **Step 5: 实现 —— 三调用点改走 _create**

在 `backend/utils/llm_client.py` 把三处 `await self._client.chat.completions.create(**kwargs)` 改为 `await self._create(**kwargs)`：
- `chat()` 内（原第 166 行）：`resp = await self._create(**kwargs)`
- `chat_stream()` 内（原第 220 行）：`stream = await self._create(**kwargs)`
- `chat_with_tools()` 内（原第 307 行）：`resp = await self._create(**kwargs)`

（流式只对「发起请求」做重试，迭代过程不重试——`_create` 返回的是 stream 对象，语义安全。）

- [ ] **Step 6: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/llm/test_llm_client_resilience.py -v`
Expected: PASS（2 passed）。

- [ ] **Step 7: 回归 —— 全量跑一次**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS（前面所有用例 + 本任务 2 个）。

- [ ] **Step 8: Commit**

```bash
git add backend/config.py backend/utils/llm_client.py tests/llm/test_llm_client_resilience.py
git commit -m "feat(llm): LLMClient 接入重试+超时（关闭 SDK 内置重试，统一 _create）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: 新版 curated 兜底模型列表（`backend/llm/curated_models.py`）

**Files:**
- Create: `backend/llm/curated_models.py`
- Modify: `backend/utils/providers.py:41-103`（各 provider `models` 改引用 curated）
- Test: `tests/llm/test_curated_models.py`

**Interfaces:**
- Consumes: 无。
- Produces:
  - `CURATED_MODELS: dict[str, list[str]]` —— provider_id → 模型 id 列表（已剔除过时项）。
  - `def curated_models_for(provider_id: str) -> list[str]` —— 取某 provider 的 curated 列表（未知返回 `[]`）。

- [ ] **Step 1: 写失败测试**

Create `tests/llm/test_curated_models.py`:
```python
from backend.llm.curated_models import CURATED_MODELS, curated_models_for


def test_known_providers_present():
    for pid in ("deepseek", "qwen", "glm", "kimi", "openai", "gemini"):
        assert pid in CURATED_MODELS
        assert curated_models_for(pid), f"{pid} 应有非空 curated 列表"


def test_unknown_provider_returns_empty():
    assert curated_models_for("nope") == []


def test_no_known_dead_models():
    # 显式确认已剔除已知过时项
    flat = [m for lst in CURATED_MODELS.values() for m in lst]
    assert "gemini-2.5-flash-preview-05-20" not in flat


def test_deepseek_has_chat_and_reasoner():
    ds = curated_models_for("deepseek")
    assert "deepseek-chat" in ds
    assert "deepseek-reasoner" in ds
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/llm/test_curated_models.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'backend.llm.curated_models'`）。

- [ ] **Step 3: 实现**

Create `backend/llm/curated_models.py`:
```python
"""Curated 兜底模型列表。

仅在「动态发现失败/不支持」时作为兜底。运行时优先用 ModelCatalog 拉到的
真实 /models 列表。这里只保证「不至于过时到全是死模型」，并剔除已知下线项。
"""

from __future__ import annotations

CURATED_MODELS: dict[str, list[str]] = {
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "qwen": ["qwen-max-latest", "qwen-plus-latest", "qwen-turbo-latest", "qwen-max", "qwen-plus", "qwen-turbo"],
    "glm": ["glm-4-plus", "glm-4-air", "glm-4-flash", "glm-4-long"],
    "kimi": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini"],
    "gemini": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
    # doubao 需 endpoint_id、custom 用户自填：留空
    "doubao": [],
    "custom": [],
}


def curated_models_for(provider_id: str) -> list[str]:
    """返回某 provider 的 curated 兜底模型列表（未知返回空列表）。"""
    return list(CURATED_MODELS.get(provider_id, []))
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/llm/test_curated_models.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 5: 让 providers.py 引用 curated（去掉写死的过时列表）**

Modify `backend/utils/providers.py`：
顶部 import 区新增：
```python
from backend.llm.curated_models import curated_models_for
```
把各 `ProviderInfo(...)` 里的 `models=[...]` 字面量替换为 `models=curated_models_for("<id>")`，并把 `default_model` 改为对应 curated 列表的首个稳定项（deepseek 保持 `deepseek-chat`，qwen 用 `qwen-plus`，glm 用 `glm-4-flash`，kimi 用 `moonshot-v1-32k`，openai 用 `gpt-4o-mini`，gemini 用 `gemini-2.5-flash`）。例如 deepseek 项：
```python
    "deepseek": ProviderInfo(
        id="deepseek",
        name="DeepSeek",
        base_url="https://api.deepseek.com",
        default_model="deepseek-chat",
        models=curated_models_for("deepseek"),
        supports_thinking=True,
        thinking_field="reasoning_content",
    ),
```
（`gemini` 的 `default_model` 从死掉的 `gemini-2.0-flash` 保留或改 `gemini-2.5-flash` 均可，本步统一改 `gemini-2.5-flash`；`glm` 的 `supports_tools=False`、`free_tier=True` 保持不变。）

- [ ] **Step 6: 验证 providers 不再含死模型**

Run: `.venv/bin/python -c "from backend.utils.providers import list_providers; import json; ms=[m for p in list_providers() for m in p['models']]; print(ms); assert 'gemini-2.5-flash-preview-05-20' not in ms; print('OK')"`
Expected: 打印模型列表 + `OK`。

- [ ] **Step 7: Commit**

```bash
git add backend/llm/curated_models.py backend/utils/providers.py tests/llm/test_curated_models.py
git commit -m "feat(llm): 新版 curated 兜底模型列表，providers 去掉写死的过时模型

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: 动态模型发现 ModelCatalog（`backend/llm/catalog.py`）

**Files:**
- Modify: `backend/config.py`（新增 `MODEL_CATALOG_TTL`）
- Create: `backend/llm/catalog.py`
- Test: `tests/llm/test_catalog.py`

**Interfaces:**
- Consumes: `backend.llm.curated_models.curated_models_for`；`backend.config.MODEL_CATALOG_TTL`。
- Produces:
  - `@dataclass ModelInfo: id: str; provider_id: str; source: str`（`source` ∈ `{"dynamic", "curated"}`）。
  - `class ModelCatalog`：
    - `__init__(self, *, ttl=MODEL_CATALOG_TTL, fetcher=None, time_fn=time.monotonic)`；`fetcher: Callable[[str, str], Awaitable[list[str]]]`（参数 `base_url, api_key` → 模型 id 列表），默认走 httpx。
    - `async def list_models(self, provider_id, api_key="", base_url="") -> list[ModelInfo]`：动态拉取成功 → `source="dynamic"` 并按 `(provider_id, base_url)` 缓存 TTL；失败/无 key/无 url → 回落 curated（`source="curated"`，`logger.warning`），不缓存失败。
    - `async def _httpx_fetch_models(base_url, api_key) -> list[str]`：`GET {base_url}/models`（带 `Authorization: Bearer`），解析 `data[].id`。
  - 模块级单例 `model_catalog = ModelCatalog()`。

- [ ] **Step 1: 加 TTL 配置**

Modify `backend/config.py` — 紧接 Task 4 新增的 LLM 韧性配置后加：
```python
MODEL_CATALOG_TTL = int(os.environ.get("MODEL_CATALOG_TTL", "21600"))  # 6h
```

- [ ] **Step 2: 写失败测试**

Create `tests/llm/test_catalog.py`:
```python
import httpx
import pytest
import respx

from backend.llm.catalog import ModelCatalog, ModelInfo


def _clock():
    state = {"t": 0.0}

    def now():
        return state["t"]

    return state, now


async def test_dynamic_fetch_sets_source_dynamic():
    async def fetcher(base_url, api_key):
        return ["m-a", "m-b"]

    cat = ModelCatalog(fetcher=fetcher)
    out = await cat.list_models("deepseek", api_key="k", base_url="https://api/v1")
    assert [m.id for m in out] == ["m-a", "m-b"]
    assert all(m.source == "dynamic" for m in out)
    assert all(isinstance(m, ModelInfo) for m in out)


async def test_fetch_failure_falls_back_to_curated():
    async def fetcher(base_url, api_key):
        raise httpx.ConnectError("refused")

    cat = ModelCatalog(fetcher=fetcher)
    out = await cat.list_models("deepseek", api_key="k", base_url="https://api/v1")
    ids = [m.id for m in out]
    assert "deepseek-chat" in ids
    assert all(m.source == "curated" for m in out)


async def test_missing_credentials_uses_curated_without_fetch():
    called = {"n": 0}

    async def fetcher(base_url, api_key):
        called["n"] += 1
        return ["should-not-happen"]

    cat = ModelCatalog(fetcher=fetcher)
    out = await cat.list_models("deepseek", api_key="", base_url="")
    assert called["n"] == 0
    assert all(m.source == "curated" for m in out)


async def test_cache_hit_within_ttl():
    calls = {"n": 0}

    async def fetcher(base_url, api_key):
        calls["n"] += 1
        return ["m-a"]

    state, now = _clock()
    cat = ModelCatalog(fetcher=fetcher, ttl=100, time_fn=now)
    await cat.list_models("deepseek", api_key="k", base_url="https://api/v1")
    state["t"] = 50  # < ttl
    await cat.list_models("deepseek", api_key="k", base_url="https://api/v1")
    assert calls["n"] == 1  # 第二次命中缓存


async def test_cache_expires_after_ttl():
    calls = {"n": 0}

    async def fetcher(base_url, api_key):
        calls["n"] += 1
        return ["m-a"]

    state, now = _clock()
    cat = ModelCatalog(fetcher=fetcher, ttl=100, time_fn=now)
    await cat.list_models("deepseek", api_key="k", base_url="https://api/v1")
    state["t"] = 150  # > ttl
    await cat.list_models("deepseek", api_key="k", base_url="https://api/v1")
    assert calls["n"] == 2


@respx.mock
async def test_httpx_fetcher_parses_openai_shape():
    route = respx.get("https://api.test.local/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "x-1"}, {"id": "x-2"}]})
    )
    cat = ModelCatalog()
    ids = await cat._httpx_fetch_models("https://api.test.local/v1", "secret")
    assert ids == ["x-1", "x-2"]
    assert route.called
    # 带上 Authorization 头
    assert route.calls.last.request.headers["authorization"] == "Bearer secret"
```

- [ ] **Step 3: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/llm/test_catalog.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'backend.llm.catalog'`）。

- [ ] **Step 4: 实现**

Create `backend/llm/catalog.py`:
```python
"""动态模型发现：运行时拉取 provider 的 /models 列表，curated 兜底。

优先 GET {base_url}/models（OpenAI 兼容；Gemini 用其 /v1beta/openai/models 同样兼容），
成功则缓存 TTL；失败/缺凭证则回落 curated 列表并告警。能力标志仍由 providers.py
的 curated 元数据维护——这里只刷新「有哪些 model id」。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx

from backend.config import MODEL_CATALOG_TTL
from backend.llm.curated_models import curated_models_for

logger = logging.getLogger(__name__)

Fetcher = Callable[[str, str], Awaitable[list[str]]]


@dataclass
class ModelInfo:
    """一个可选模型。source 标记来源（dynamic=实时拉取 / curated=兜底）。"""

    id: str
    provider_id: str
    source: str  # "dynamic" | "curated"


class ModelCatalog:
    """带 TTL 缓存的模型目录。"""

    def __init__(
        self,
        *,
        ttl: int = MODEL_CATALOG_TTL,
        fetcher: Fetcher | None = None,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl
        self._fetcher: Fetcher = fetcher or self._httpx_fetch_models
        self._now = time_fn
        # key=(provider_id, base_url) -> (fetched_at, [model_id,...])
        self._cache: dict[tuple[str, str], tuple[float, list[str]]] = {}

    async def list_models(
        self,
        provider_id: str,
        api_key: str = "",
        base_url: str = "",
    ) -> list[ModelInfo]:
        """返回某 provider 的可选模型。优先动态，失败回落 curated。"""
        # 无凭证/无 url：直接 curated，不尝试拉取
        if not api_key or not base_url:
            return self._curated(provider_id)

        cache_key = (provider_id, base_url)
        cached = self._cache.get(cache_key)
        if cached and (self._now() - cached[0]) < self._ttl:
            return [ModelInfo(mid, provider_id, "dynamic") for mid in cached[1]]

        try:
            ids = await self._fetcher(base_url, api_key)
        except Exception as exc:  # noqa: BLE001 - 任意拉取失败都回落
            logger.warning(
                "动态模型发现失败（provider=%s base_url=%s），回落 curated：%s",
                provider_id, base_url, exc,
            )
            return self._curated(provider_id)

        if not ids:
            logger.warning(
                "动态模型发现返回空（provider=%s），回落 curated", provider_id
            )
            return self._curated(provider_id)

        self._cache[cache_key] = (self._now(), ids)
        return [ModelInfo(mid, provider_id, "dynamic") for mid in ids]

    def _curated(self, provider_id: str) -> list[ModelInfo]:
        return [
            ModelInfo(mid, provider_id, "curated")
            for mid in curated_models_for(provider_id)
        ]

    async def _httpx_fetch_models(self, base_url: str, api_key: str) -> list[str]:
        """GET {base_url}/models，解析 OpenAI 兼容的 data[].id。"""
        url = base_url.rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {api_key}"}
        async with httpx.AsyncClient(trust_env=False, timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
        data = payload.get("data", []) if isinstance(payload, dict) else []
        return [item["id"] for item in data if isinstance(item, dict) and "id" in item]


# 单例
model_catalog = ModelCatalog()
```

- [ ] **Step 5: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/llm/test_catalog.py -v`
Expected: PASS（6 passed）。

- [ ] **Step 6: Commit**

```bash
git add backend/config.py backend/llm/catalog.py tests/llm/test_catalog.py
git commit -m "feat(llm): ModelCatalog 动态模型发现（/models + TTL 缓存 + curated 兜底）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: 暴露端点 `POST /api/settings/models`

**Files:**
- Modify: `backend/api/settings.py`（新增请求模型 + 端点）
- Test: `tests/llm/test_settings_models_api.py`

**Interfaces:**
- Consumes: `backend.llm.catalog.model_catalog`。
- Produces: `POST /api/settings/models`，请求体 `{provider_id, api_key, base_url}`，响应 `{"models": [{"id","provider_id","source"}...], "source": "dynamic"|"curated"}`（`source` 取列表整体来源：全 dynamic 则 dynamic，否则 curated）。

- [ ] **Step 1: 写失败测试**

Create `tests/llm/test_settings_models_api.py`:
```python
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.settings as settings_module


def _make_client(monkeypatch, fetcher):
    # 用注入了假 fetcher 的全新 catalog 替换端点引用的单例
    from backend.llm.catalog import ModelCatalog

    monkeypatch.setattr(settings_module, "model_catalog", ModelCatalog(fetcher=fetcher))
    app = FastAPI()
    app.include_router(settings_module.router)
    return TestClient(app)


def test_models_endpoint_dynamic(monkeypatch):
    async def fetcher(base_url, api_key):
        return ["m-a", "m-b"]

    client = _make_client(monkeypatch, fetcher)
    resp = client.post(
        "/api/settings/models",
        json={"provider_id": "deepseek", "api_key": "k", "base_url": "https://api/v1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert [m["id"] for m in body["models"]] == ["m-a", "m-b"]
    assert body["source"] == "dynamic"


def test_models_endpoint_fallback_curated(monkeypatch):
    async def fetcher(base_url, api_key):
        raise RuntimeError("down")

    client = _make_client(monkeypatch, fetcher)
    resp = client.post(
        "/api/settings/models",
        json={"provider_id": "deepseek", "api_key": "k", "base_url": "https://api/v1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "curated"
    assert any(m["id"] == "deepseek-chat" for m in body["models"])
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/llm/test_settings_models_api.py -v`
Expected: FAIL（404：端点尚不存在）。

- [ ] **Step 3: 实现**

Modify `backend/api/settings.py`：
顶部 import 区新增：
```python
from backend.llm.catalog import model_catalog
```
新增请求模型（放在 `VerifyResponse` 之后）：
```python
class ModelsRequest(BaseModel):
    provider_id: str = Field(..., description="Provider ID")
    api_key: str = Field("", description="API key（动态发现用；空则直接 curated）")
    base_url: str = Field("", description="Override base URL（空则用 provider 默认）")
```
新增端点（放在文件末尾）：
```python
@router.post("/models")
async def get_models(req: ModelsRequest):
    """返回某 provider 的可选模型列表（优先动态发现，失败回落 curated）。"""
    from backend.utils.providers import get_provider

    base_url = req.base_url
    if not base_url:
        provider = get_provider(req.provider_id)
        base_url = provider.base_url if provider else ""

    models = await model_catalog.list_models(
        req.provider_id, api_key=req.api_key, base_url=base_url
    )
    overall = "dynamic" if models and all(m.source == "dynamic" for m in models) else "curated"
    return {
        "models": [
            {"id": m.id, "provider_id": m.provider_id, "source": m.source}
            for m in models
        ],
        "source": overall,
    }
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/llm/test_settings_models_api.py -v`
Expected: PASS（2 passed）。

- [ ] **Step 5: 全量回归**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS（全部用例：smoke 3 + errors 10 + retry 5 + resilience 2 + curated 4 + catalog 6 + api 2）。

- [ ] **Step 6: Commit**

```bash
git add backend/api/settings.py tests/llm/test_settings_models_api.py
git commit -m "feat(api): 新增 POST /api/settings/models 动态模型列表端点

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage（对照 spec 第 5.6 / 第 9 期第 1 项 / 决策⑦）**
- 韧性客户端（退避/超时/瞬时-永久分类）→ Task 2/3/4 ✓
- 动态模型发现（`/models` + TTL + curated 兜底）→ Task 6 ✓
- Gemini 兼容端点 → `_httpx_fetch_models` 用 `{base_url}/models`，Gemini 的 base_url 已是 `.../v1beta/openai/`，拼出 `.../v1beta/openai/models`，兼容 ✓
- curated 静态列表更新 → Task 5 ✓
- 经 `/api/settings` 暴露给前端 → Task 7 ✓
- 能力标志保留为 curated 元数据（不动态探测）→ catalog 只返回 model id，`supports_tools` 等仍在 providers.py ✓
- 前端适配：本期仅新增端点，未改既有契约；前端下拉接线属后续/前端工单，spec 已将前端列为「最小适配」非目标主体 ✓（如需，执行时附带一个前端 store 调用 `POST /api/settings/models` 的小改）

**2. Placeholder scan**：无 TBD/TODO；每个代码步骤均含完整可粘贴代码；每个测试步骤均含完整断言。✓

**3. Type consistency**：
- `with_retry(fn, *, max_attempts, base_delay, max_delay, sleep)` 在 Task 3 定义、Task 4 `_create` 按此调用（仅传 `max_attempts`/`base_delay`，其余默认）✓
- `classify_exception` 返回 `LLMError` 子类，Task 3/4 据 `isinstance(PermanentLLMError)` 决策 ✓
- `ModelInfo(id, provider_id, source)` 字段在 catalog 定义、Task 7 端点按此序列化（`m.id/m.provider_id/m.source`）✓
- `curated_models_for(provider_id)` 在 Task 5 定义、Task 6 catalog 与 providers.py 均按此签名调用 ✓
- `model_catalog` 单例在 Task 6 定义、Task 7 import 并被测试 monkeypatch 替换 ✓

无不一致，无遗漏 spec 项（本期范围内）。
