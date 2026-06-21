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
