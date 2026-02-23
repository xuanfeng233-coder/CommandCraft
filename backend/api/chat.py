"""Chat API endpoint with SSE streaming + session management."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from backend.config import MAX_CONTEXT_MESSAGES, SUBSCRIPTION_ENABLED
from backend.models.database import session_db
from backend.models.schemas import ChatRequest
from backend.orchestrator.orchestrator import orchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


async def _event_generator(
    request: ChatRequest,
    device_fp: str = "",
) -> AsyncGenerator[dict[str, Any], None]:
    """Wrap orchestrator output into SSE-formatted events."""
    # --- Decide which LLM client to use ---
    # Priority: subscription (if active & within limits) → user's own API key → error
    sub_token = None
    use_subscription = False
    sub_exhausted_reason = ""

    if device_fp and SUBSCRIPTION_ENABLED:
        from backend.subscription.database import subscription_db
        from backend.subscription.llm_context import (
            is_subscription_client_ready,
            set_subscription_context,
        )

        if is_subscription_client_ready():
            limits = await subscription_db.check_limits(device_fp)
            if limits.get("allowed"):
                sub_token = set_subscription_context()
                use_subscription = True
                logger.info(
                    "Subscription active for %s: plan=%s usage=%s/%s",
                    device_fp[:8],
                    limits.get("plan_name"),
                    limits.get("daily_used"),
                    limits.get("daily_limit"),
                )
            else:
                sub_exhausted_reason = limits.get("reason", "")
                logger.info(
                    "Subscription exhausted for %s: reason=%s",
                    device_fp[:8], sub_exhausted_reason,
                )

    # Fallback: check if user's own API key is available
    if not use_subscription:
        from backend.utils.llm_client import llm_client
        if not llm_client.is_configured:
            if sub_exhausted_reason == "daily_limit":
                msg = "今日订阅用量已达上限，请明天再试或在设置中配置自己的 API Key"
            elif sub_exhausted_reason == "monthly_limit":
                msg = "本月订阅用量已达上限，请在设置中配置自己的 API Key 或升级套餐"
            else:
                msg = "请先兑换订阅码或在设置中配置 API Key"
            yield {
                "event": "error",
                "data": json.dumps({"message": msg}, ensure_ascii=False),
            }
            return

    # Resolve or create session
    session_id = request.session_id
    if session_id:
        session = await session_db.get_session(session_id)
        if not session:
            session_id = None
    if not session_id:
        session_id = await session_db.create_session(
            title=request.message[:50],
        )

    # Save user message
    await session_db.add_message(
        session_id=session_id,
        role="user",
        content=request.message,
    )

    # Get conversation context
    context = await session_db.get_recent_context(
        session_id, MAX_CONTEXT_MESSAGES
    )

    # Collect assistant response for saving
    collected_thinking = ""
    collected_result: dict[str, Any] = {}

    try:
        async for event in orchestrator.process_message_stream(
            user_input=request.message,
            session_context=context,
            session_id=session_id,
            task_id=request.task_id,
        ):
            event_type = event.get("event", "content")
            data = event.get("data", {})

            # Collect for persistence
            if event_type == "thinking":
                collected_thinking += data.get("text", "")
            elif event_type == "content":
                collected_result = data
            elif event_type == "done":
                data["session_id"] = session_id

            yield {
                "event": event_type,
                "data": json.dumps(data, ensure_ascii=False),
            }

        # Save assistant message after stream completes
        msg_type = collected_result.get("type", "")
        command = collected_result.get("command")
        questions = collected_result.get("questions")
        content = collected_result.get("message", "")
        await session_db.add_message(
            session_id=session_id,
            role="assistant",
            content=content or "",
            msg_type=msg_type or None,
            command=command,
            questions=questions,
            thinking=collected_thinking or None,
        )

        # Increment subscription usage after successful stream
        if use_subscription and device_fp:
            try:
                from backend.subscription.database import subscription_db
                await subscription_db.increment_usage(device_fp)
            except Exception:
                logger.warning("Failed to increment subscription usage", exc_info=True)

    except Exception as e:
        logger.exception("Error during chat processing")
        yield {
            "event": "error",
            "data": json.dumps({"message": str(e)}, ensure_ascii=False),
        }
    finally:
        if sub_token is not None:
            from backend.subscription.llm_context import clear_subscription_context
            clear_subscription_context(sub_token)


@router.post("/chat")
async def chat(request: ChatRequest, raw_request: Request):
    """Send a message and receive SSE streaming response."""
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")

    device_fp = raw_request.headers.get("X-Device-Fp", "")

    return EventSourceResponse(
        _event_generator(request, device_fp=device_fp),
        media_type="text/event-stream",
    )


# --- Session history endpoints ---


@router.get("/chat/history")
async def list_sessions(limit: int = 50):
    """List recent chat sessions."""
    sessions = await session_db.list_sessions(limit)
    return {"sessions": sessions}


@router.get("/chat/{session_id}")
async def get_session(session_id: str):
    """Get a session and its messages."""
    session = await session_db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = await session_db.get_messages(session_id)
    return {"session": session, "messages": messages}


@router.delete("/chat/{session_id}")
async def delete_session(session_id: str):
    """Delete a session and its messages."""
    deleted = await session_db.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"success": True}
