"""Per-request LLM client override via contextvars.

Allows subscription users to transparently use the developer's LLM
without changing agent method signatures.
"""

from __future__ import annotations

import contextvars
import logging

from backend.utils.llm_client import LLMClient, llm_client

logger = logging.getLogger(__name__)

_override: contextvars.ContextVar[LLMClient | None] = contextvars.ContextVar(
    "sub_llm_client", default=None
)

_sub_client: LLMClient | None = None


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


def get_llm_client() -> LLMClient:
    """Return the subscription client if contextvar is set, else the global client.

    Agents call this instead of importing ``llm_client`` directly.
    """
    override = _override.get(None)
    return override if override is not None else llm_client


def set_subscription_context() -> contextvars.Token:
    """Activate the subscription LLM client for the current context."""
    return _override.set(_sub_client)


def clear_subscription_context(token: contextvars.Token) -> None:
    """Restore the previous LLM client after the request."""
    _override.reset(token)


def is_subscription_client_ready() -> bool:
    """Check if the subscription LLM client has been initialized."""
    return _sub_client is not None and _sub_client.is_configured
