"""Planner — calls LLM to decompose user input into a typed Decomposition.

Control flow:
- Loop 1 + max_repairs times.
- Each iteration: call client.chat (NO try/except — LLMError propagates as transport error).
- Extract JSON via BaseSkill.extract_json; None → schema repair message.
- Validate with Decomposition.model_validate + validate_graph.
  On success: return (Decomposition, thinking).
  On failure: append assistant msg + user repair msg with exact error text; continue.
- On exhaustion: raise PlannerParseError (never a silent fallback).
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from backend.agents.main_agent import _DECOMPOSE_PROMPT, _DECOMPOSE_PROMPT_JAVA
from backend.agents.planner_schemas import Decomposition, GraphError, validate_graph
from backend.config import DECOMPOSE_MAX_TOKENS
from backend.skills.base import BaseSkill
from backend.subscription.llm_context import get_llm_client

logger = logging.getLogger(__name__)


class PlannerParseError(Exception):
    """Raised when schema/JSON repair is exhausted (not a transport error)."""


class Planner:
    """Stateless planner: calls the LLM, validates, repairs, returns typed Decomposition."""

    async def plan(
        self,
        user_input: str,
        session_context: str = "",
        *,
        client: Any | None = None,
        edition: str = "bedrock",
        max_repairs: int = 2,
    ) -> tuple[Decomposition, str]:
        """Decompose user input into a typed Decomposition.

        Args:
            user_input: The user's natural language request.
            session_context: Optional conversation history context.
            client: Optional LLM client override; uses get_llm_client() if None.
            edition: 'bedrock' or 'java'.
            max_repairs: Maximum number of repair attempts after initial failure.

        Returns:
            (Decomposition, thinking) on success.

        Raises:
            TransientLLMError / PermanentLLMError: transport errors (propagate, no catch).
            PlannerParseError: schema/JSON repair exhausted.
        """
        _client = client or get_llm_client()
        system_prompt = _DECOMPOSE_PROMPT_JAVA if edition == "java" else _DECOMPOSE_PROMPT

        # Build initial message list
        msgs: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        if session_context:
            msgs.append({
                "role": "system",
                "content": f"## 对话历史\n{session_context}",
            })
        msgs.append({"role": "user", "content": user_input})

        last_error: Exception | None = None

        for attempt in range(1 + max_repairs):
            # DO NOT catch LLMError — transport errors propagate immediately.
            resp = await _client.chat(msgs, max_tokens=DECOMPOSE_MAX_TOKENS, think=True)

            msg = resp.get("message", {})
            thinking: str = msg.get("thinking", "")
            content: str = msg.get("content", "")

            logger.debug(
                "Planner attempt %d: thinking=%d chars, content=%d chars",
                attempt, len(thinking), len(content),
            )

            # --- JSON extraction ---
            data = BaseSkill.extract_json(content)
            if data is None:
                repair_text = "输出不是合法 JSON，请只输出一个 JSON 对象"
                last_error = ValueError(repair_text)
                logger.warning("Planner attempt %d: JSON extraction failed", attempt)
                # Append assistant response + repair request for next iteration
                msgs.append({"role": "assistant", "content": content})
                msgs.append({"role": "user", "content": repair_text})
                continue

            # --- Schema + graph validation ---
            try:
                d = Decomposition.model_validate(data)
                validate_graph(d)
                return (d, thinking)
            except (ValidationError, GraphError, TypeError) as e:
                last_error = e
                error_text = e.message if isinstance(e, GraphError) else str(e)
                logger.warning(
                    "Planner attempt %d: validation error: %s", attempt, error_text
                )
                repair_msg = f"{error_text}，只输出修正后的 JSON 对象"
                msgs.append({"role": "assistant", "content": content})
                msgs.append({"role": "user", "content": repair_msg})
                continue

        # All attempts exhausted
        raise PlannerParseError(str(last_error))
