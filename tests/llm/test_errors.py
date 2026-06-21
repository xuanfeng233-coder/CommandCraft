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


def test_cancelled_error_is_reraised():
    """classify_exception 绝不能把 CancelledError 包装为 LLMError。"""
    import asyncio as _asyncio

    with pytest.raises(_asyncio.CancelledError):
        classify_exception(_asyncio.CancelledError())
