"""Unified cloud LLM client using the OpenAI SDK.

Replaces ollama_client.py.  Provides the same return format so that
agent code requires minimal changes.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, AsyncGenerator

import httpx
from openai import AsyncOpenAI

from backend.config import MODEL_TEMPERATURE

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_thinking_tags(text: str) -> tuple[str, str]:
    """Separate <think>...</think> content from the final answer.

    Returns (thinking, answer).
    """
    match = re.search(r"<think>(.*?)</think>", text, re.DOTALL)
    if match:
        thinking = match.group(1).strip()
        answer = text[: match.start()] + text[match.end() :]
        return thinking, answer.strip()
    return "", text.strip()


def _prep_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prepare messages for the OpenAI API.

    - Convert tool_calls arguments from dict to JSON string.
    - Ensure tool response messages have a tool_call_id.
    """
    prepped: list[dict[str, Any]] = []
    # Collect tool_call ids from assistant messages so we can match them to
    # subsequent tool-role messages.
    pending_tool_call_ids: list[str] = []

    for msg in messages:
        m = dict(msg)  # shallow copy
        role = m.get("role", "")

        if role == "assistant" and "tool_calls" in m and m["tool_calls"]:
            tcs = []
            for tc in m["tool_calls"]:
                tc_copy = dict(tc)
                func = dict(tc_copy.get("function", {}))
                # Ensure arguments is a JSON string
                if isinstance(func.get("arguments"), dict):
                    func["arguments"] = json.dumps(func["arguments"], ensure_ascii=False)
                tc_copy["function"] = func
                # Generate an id if missing
                if "id" not in tc_copy or not tc_copy["id"]:
                    tc_copy["id"] = f"call_{len(prepped)}_{len(tcs)}"
                tcs.append(tc_copy)
                pending_tool_call_ids.append(tc_copy["id"])
            m["tool_calls"] = tcs
            # OpenAI requires content to be null (not empty string) when tool_calls present
            if not m.get("content"):
                m["content"] = None

        elif role == "tool":
            # Assign tool_call_id from the pending queue
            if "tool_call_id" not in m or not m["tool_call_id"]:
                if pending_tool_call_ids:
                    m["tool_call_id"] = pending_tool_call_ids.pop(0)
                else:
                    m["tool_call_id"] = f"call_fallback_{len(prepped)}"

        prepped.append(m)
    return prepped


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class LLMClient:
    """Async OpenAI-compatible LLM client."""

    def __init__(self) -> None:
        self._client: AsyncOpenAI | None = None
        self._model: str = ""
        self._provider_id: str = ""
        self._thinking_field: str = ""  # e.g. "reasoning_content" for DeepSeek

    # -- Configuration -------------------------------------------------------

    def configure(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        provider_id: str = "",
        thinking_field: str = "",
    ) -> None:
        """Create / recreate the underlying AsyncOpenAI instance."""
        # BUG-8 fix: bypass Windows system proxy
        http_client = httpx.AsyncClient(trust_env=False)
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            http_client=http_client,
        )
        self._model = model
        self._provider_id = provider_id
        self._thinking_field = thinking_field
        logger.info(
            "LLMClient configured: provider=%s model=%s base_url=%s",
            provider_id, model, base_url,
        )

    @property
    def is_configured(self) -> bool:
        return self._client is not None and bool(self._model)

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider_id(self) -> str:
        return self._provider_id

    # -- Chat (non-streaming) ------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = MODEL_TEMPERATURE,
        max_tokens: int | None = None,
        think: bool | None = None,
    ) -> dict[str, Any]:
        """Non-streaming chat. Returns Ollama-compatible format:

        {"message": {"role": "assistant", "content": "...", "thinking": "..."}}
        """
        if not self._client:
            raise RuntimeError("LLM client not configured")

        prepped = _prep_messages(messages)
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": prepped,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        logger.debug("LLM chat: model=%s messages=%d", self._model, len(prepped))
        resp = await self._client.chat.completions.create(**kwargs)

        choice = resp.choices[0]
        content = choice.message.content or ""
        thinking = ""

        # Extract thinking from provider-specific field
        if self._thinking_field:
            thinking = getattr(choice.message, self._thinking_field, "") or ""

        # Fallback: parse <think> tags from content
        if not thinking and content:
            thinking, content = parse_thinking_tags(content)

        return {
            "message": {
                "role": "assistant",
                "content": content,
                "thinking": thinking,
            }
        }

    # -- Chat (streaming) ----------------------------------------------------

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = MODEL_TEMPERATURE,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[dict[str, str], None]:
        """Streaming chat. Yields Ollama-compatible chunks:

        {"thinking": "token"} / {"content": "token"} / {"done": "true"}
        """
        if not self._client:
            raise RuntimeError("LLM client not configured")

        prepped = _prep_messages(messages)
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": prepped,
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        logger.debug("LLM chat_stream: model=%s messages=%d", self._model, len(prepped))

        # Track whether we're inside <think> tags for providers that embed them
        in_think_tag = False
        content_buffer = ""

        stream = await self._client.chat.completions.create(**kwargs)
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            # Provider-specific thinking field (DeepSeek reasoner)
            if self._thinking_field:
                reasoning = getattr(delta, self._thinking_field, None)
                if reasoning:
                    yield {"thinking": reasoning}

            text = delta.content or ""
            if not text:
                continue

            # Parse <think> tags in-stream for providers that embed them
            if not self._thinking_field:
                # Process character by character for tag detection
                for char in text:
                    content_buffer += char
                    if content_buffer.endswith("<think>"):
                        in_think_tag = True
                        # Remove the tag from buffer
                        content_buffer = content_buffer[:-7]
                        if content_buffer:
                            yield {"content": content_buffer}
                            content_buffer = ""
                    elif content_buffer.endswith("</think>"):
                        in_think_tag = False
                        # Remove the tag from buffer and emit as thinking
                        content_buffer = content_buffer[:-8]
                        if content_buffer:
                            yield {"thinking": content_buffer}
                            content_buffer = ""
                    elif len(content_buffer) > 20:
                        # Flush buffer
                        if in_think_tag:
                            yield {"thinking": content_buffer}
                        else:
                            yield {"content": content_buffer}
                        content_buffer = ""
            else:
                yield {"content": text}

        # Flush remaining buffer
        if content_buffer:
            if in_think_tag:
                yield {"thinking": content_buffer}
            else:
                yield {"content": content_buffer}

        yield {"done": "true"}

    # -- Chat with tools (non-streaming) ------------------------------------

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        temperature: float = MODEL_TEMPERATURE,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Non-streaming chat with tool calling. Returns Ollama-compatible format:

        {"message": {"role": "assistant", "content": "...", "thinking": "...",
                      "tool_calls": [{"id": "...", "function": {"name": "...", "arguments": {...}}}]}}
        """
        if not self._client:
            raise RuntimeError("LLM client not configured")

        prepped = _prep_messages(messages)
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": prepped,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = tools

        logger.debug(
            "LLM chat_with_tools: model=%s tools=%d messages=%d",
            self._model, len(tools), len(prepped),
        )
        resp = await self._client.chat.completions.create(**kwargs)

        choice = resp.choices[0]
        content = choice.message.content or ""
        thinking = ""

        # Extract thinking
        if self._thinking_field:
            thinking = getattr(choice.message, self._thinking_field, "") or ""
        if not thinking and content:
            thinking, content = parse_thinking_tags(content)

        # Convert tool calls to Ollama-compatible format
        tool_calls_out: list[dict[str, Any]] = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                # Parse arguments from JSON string to dict
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    args = {}
                tool_calls_out.append({
                    "id": tc.id,
                    "function": {
                        "name": tc.function.name,
                        "arguments": args,
                    },
                })

        result: dict[str, Any] = {
            "message": {
                "role": "assistant",
                "content": content,
                "thinking": thinking,
            }
        }
        if tool_calls_out:
            result["message"]["tool_calls"] = tool_calls_out

        return result

    # -- Health check --------------------------------------------------------

    async def check_health(self) -> tuple[bool, bool]:
        """Check API reachability and model availability.

        Returns (api_ok, model_ok).  Both True if a simple completion succeeds.
        """
        if not self._client:
            return False, False
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            return True, bool(resp.choices)
        except Exception as e:
            logger.warning("LLM health check failed: %s", e)
            # Distinguish API-level vs model-level errors
            err_str = str(e).lower()
            if "model" in err_str or "not found" in err_str:
                return True, False
            return False, False


# Singleton
llm_client = LLMClient()
