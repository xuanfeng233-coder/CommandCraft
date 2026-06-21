"""Per-request LLM client override via contextvars.

Allows subscription users to transparently use the developer's LLM
without changing agent method signatures.

Priority: build_override > sub_override > global
"""

from __future__ import annotations

import contextvars
import logging

from backend.utils.llm_client import LLMClient, llm_client

logger = logging.getLogger(__name__)

_override: contextvars.ContextVar[LLMClient | None] = contextvars.ContextVar(
    "sub_llm_client", default=None
)

_build_override: contextvars.ContextVar[LLMClient | None] = contextvars.ContextVar(
    "build_llm_client", default=None
)

_sub_client: LLMClient | None = None
_build_client: LLMClient | None = None
_build_chat_client: LLMClient | None = None


def init_subscription_client(
    api_key: str, base_url: str, model: str
) -> None:
    """Called once at startup. Creates a dedicated LLMClient for subscribers."""
    global _sub_client
    _sub_client = LLMClient()
    _sub_client.configure(
        api_key=api_key,
        base_url=base_url,
        model=model,
        provider_id="deepseek",
        thinking_field="reasoning_content",
    )
    logger.info("Subscription LLM client initialized: model=%s", model)


def init_build_client(
    api_key: str, base_url: str, model: str
) -> None:
    """Called once at startup. Creates a dedicated LLMClient for build mode (deepseek-reasoner)."""
    global _build_client
    _build_client = LLMClient()
    _build_client.configure(
        api_key=api_key,
        base_url=base_url,
        model=model,
        provider_id="deepseek",
        thinking_field="reasoning_content",
    )
    logger.info("Build LLM client initialized: model=%s", model)


def init_build_chat_client(
    api_key: str, base_url: str, model: str
) -> None:
    """Called once at startup. Creates a dedicated LLMClient for build chat tasks (deepseek-chat)."""
    global _build_chat_client
    _build_chat_client = LLMClient()
    _build_chat_client.configure(
        api_key=api_key,
        base_url=base_url,
        model=model,
        provider_id="deepseek",
        thinking_field="reasoning_content",
    )
    logger.info("Build chat LLM client initialized: model=%s", model)


def get_build_chat_client() -> LLMClient:
    """Return the build-mode chat client (deepseek-chat).

    Used by agents that don't need the reasoner model (ClarifyAgent,
    WriteAgent, SearchAgent._verify, MainAgent.decompose in build mode).
    Falls back to the build reasoner client, then subscription, then global.
    """
    if _build_chat_client is not None and _build_chat_client.is_configured:
        return _build_chat_client
    # Fallback chain: build reasoner → subscription → global
    if _build_client is not None and _build_client.is_configured:
        return _build_client
    return get_llm_client()


def is_build_chat_client_ready() -> bool:
    """Check if the build chat LLM client has been initialized."""
    return _build_chat_client is not None and _build_chat_client.is_configured


def get_llm_client() -> LLMClient:
    """Return the highest-priority active client.

    Priority: build_override > sub_override > global.
    Agents call this instead of importing ``llm_client`` directly.
    """
    build = _build_override.get(None)
    if build is not None:
        return build
    override = _override.get(None)
    return override if override is not None else llm_client


def set_subscription_context() -> contextvars.Token:
    """Activate the subscription LLM client for the current context."""
    return _override.set(_sub_client)


def clear_subscription_context(token: contextvars.Token) -> None:
    """Restore the previous LLM client after the request."""
    _override.reset(token)


def set_build_context() -> contextvars.Token:
    """Activate the build-mode LLM client (deepseek-reasoner) for the current context."""
    return _build_override.set(_build_client)


def clear_build_context(token: contextvars.Token) -> None:
    """Restore the previous LLM client after the build request."""
    _build_override.reset(token)


def is_subscription_client_ready() -> bool:
    """Check if the subscription LLM client has been initialized."""
    return _sub_client is not None and _sub_client.is_configured


def is_build_client_ready() -> bool:
    """Check if the build LLM client has been initialized."""
    return _build_client is not None and _build_client.is_configured
