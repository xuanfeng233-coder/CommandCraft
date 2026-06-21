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
