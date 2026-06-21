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


async def test_cancelled_error_propagates_immediately():
    """asyncio.CancelledError 必须透传出 with_retry，不能被包装为 PermanentLLMError。"""
    import asyncio as _asyncio

    call_count = {"n": 0}

    async def fn():
        call_count["n"] += 1
        raise _asyncio.CancelledError()

    calls, sleep = _recording_sleep()
    with pytest.raises(_asyncio.CancelledError):
        await with_retry(fn, max_attempts=3, sleep=sleep)
    # 取消应立即放行：fn 只被调用一次，且没有 sleep
    assert call_count["n"] == 1
    assert calls == []
