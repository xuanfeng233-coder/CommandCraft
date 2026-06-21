"""Build mode API endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.auth.dependencies import OwnerContext, get_owner_context
from backend.build.build_orchestrator import build_orchestrator
from backend.build.project_manager import project_manager
from backend.config import BUILD_USE_AGENT_LOOP
from backend.models.database import session_db
from backend.models.schemas import BuildClarifyRequest, BuildConfirmRequest, BuildStartRequest
from backend.subscription.database import subscription_db
from backend.subscription.llm_context import (
    clear_build_context,
    is_build_client_ready,
    set_build_context,
    set_subscription_context,
    clear_subscription_context,
    is_subscription_client_ready,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/build", tags=["build"])


def _owns_project(proj: dict, owner: OwnerContext) -> bool:
    """Check if a project belongs to the given owner."""
    # For now, build projects only track device_fp.
    # Match by device_fp (build projects don't have user_id yet).
    return proj.get("device_fp") == owner.device_fp


async def _check_build_access(request: Request) -> OwnerContext:
    """Validate build mode access. Returns OwnerContext or raises HTTPException."""
    owner = await get_owner_context(request)
    if not owner.user_id and not owner.device_fp:
        raise HTTPException(status_code=400, detail="缺少设备标识")

    limits = await subscription_db.check_build_limits(
        device_fp=owner.device_fp, user_id=owner.user_id,
    )
    if not limits["allowed"]:
        reason = limits.get("reason", "")
        if reason == "no_subscription":
            raise HTTPException(status_code=403, detail="构建模式需要有效订阅")
        elif reason == "plan_no_build":
            raise HTTPException(status_code=403, detail="当前套餐不支持构建模式，请升级到 Pro 或 Ultra")
        elif reason == "build_limit":
            raise HTTPException(status_code=429, detail="本月构建次数已用完")
        else:
            raise HTTPException(status_code=403, detail="无法使用构建模式")

    return owner


def _make_sse_stream(async_gen):
    """Wrap an async generator into an SSE StreamingResponse."""
    import json

    async def event_stream():
        try:
            async for event in async_gen:
                event_name = event.get("event", "message")
                data = event.get("data", {})
                yield f"event: {event_name}\r\ndata: {json.dumps(data, ensure_ascii=False)}\r\n\r\n"
        except Exception as e:
            logger.error("Build SSE stream error: %s", e)
            error_data = json.dumps({"message": str(e)}, ensure_ascii=False)
            yield f"event: error\r\ndata: {error_data}\r\n\r\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/start")
async def start_build(req: BuildStartRequest, request: Request):
    """Start a new build project → SSE stream."""
    owner = await _check_build_access(request)

    # Detect edition from request header or default
    edition = request.headers.get("X-MC-Edition", "bedrock")

    # Create a session in the history DB so build chats show in history
    history_session_id = await session_db.create_session(
        title=f"[构建] {req.message[:44]}",
        device_fp=owner.device_fp,
        user_id=owner.user_id,
        edition=edition,
        mode="build",
    )
    await session_db.add_message(
        session_id=history_session_id,
        role="user",
        content=req.message,
        msg_type="build_start",
    )

    async def wrapped_stream():
        build_token = None
        sub_token = None

        if is_build_client_ready():
            build_token = set_build_context()
        elif is_subscription_client_ready():
            sub_token = set_subscription_context()

        plan_content = ""
        completed_commands: list[str] = []

        try:
            async for event in build_orchestrator.start_build(
                user_input=req.message,
                device_fp=owner.device_fp,
                session_id=req.session_id or "",
                edition=edition,
            ):
                # Capture key events for history
                event_name = event.get("event", "")
                data = event.get("data", {})
                if event_name == "build_plan":
                    plan_content = data.get("markdown_content", "")
                if event_name == "build_phase" and data.get("phase") == "completed":
                    completed_commands = data.get("commands", [])

                yield event

            # Save build result as assistant message
            summary = f"构建方案已生成"
            if completed_commands:
                summary = f"构建完成，生成了 {len(completed_commands)} 条命令"
            await session_db.add_message(
                session_id=history_session_id,
                role="assistant",
                content=summary,
                msg_type="build_result",
                thinking=plan_content[:2000] if plan_content else None,
            )
        finally:
            if build_token is not None:
                clear_build_context(build_token)
            if sub_token is not None:
                clear_subscription_context(sub_token)

    return _make_sse_stream(wrapped_stream())


@router.post("/{project_id}/clarify")
async def clarify_build(project_id: str, req: BuildClarifyRequest, request: Request):
    """User answers clarification questions -> continue generating plan -> SSE stream.

    Flag-off: normal clarify-resume flow.
    Flag-on: frontend won't call this; defensive guard returns benign done SSE.
    """
    # Defensive guard: flag-on shouldn't reach here, but return gracefully if it does.
    if BUILD_USE_AGENT_LOOP:
        async def _done_stream():
            yield {"event": "done", "data": {"project_id": project_id}}

        return _make_sse_stream(_done_stream())

    owner = await _check_build_access(request)

    # Verify ownership
    proj = await project_manager.get_project(project_id)
    if not proj or not _owns_project(proj, owner):
        raise HTTPException(status_code=404, detail="项目不存在")

    async def wrapped_stream():
        build_token = None
        sub_token = None

        if is_build_client_ready():
            build_token = set_build_context()
        elif is_subscription_client_ready():
            sub_token = set_subscription_context()

        try:
            async for event in build_orchestrator.continue_after_clarify(
                project_id=project_id,
                answers=req.answers,
            ):
                yield event
        finally:
            if build_token is not None:
                clear_build_context(build_token)
            if sub_token is not None:
                clear_subscription_context(sub_token)

    return _make_sse_stream(wrapped_stream())


@router.post("/{project_id}/confirm")
async def confirm_build(project_id: str, req: BuildConfirmRequest, request: Request):
    """Confirm plan and start execution → SSE stream."""
    owner = await _check_build_access(request)

    # Verify ownership
    proj = await project_manager.get_project(project_id)
    if not proj or not _owns_project(proj, owner):
        raise HTTPException(status_code=404, detail="项目不存在")

    async def wrapped_stream():
        build_token = None
        sub_token = None

        if is_build_client_ready():
            build_token = set_build_context()
        elif is_subscription_client_ready():
            sub_token = set_subscription_context()

        try:
            async for event in build_orchestrator.confirm_plan(
                project_id=project_id,
                plan_content=req.plan_content,
            ):
                yield event

            # Increment build usage after successful completion
            await subscription_db.increment_build_usage(
                device_fp=owner.device_fp, user_id=owner.user_id,
            )
        finally:
            if build_token is not None:
                clear_build_context(build_token)
            if sub_token is not None:
                clear_subscription_context(sub_token)

    return _make_sse_stream(wrapped_stream())


@router.put("/{project_id}/plan")
async def update_plan(project_id: str, req: BuildConfirmRequest, request: Request):
    """Update plan content without starting execution."""
    owner = await get_owner_context(request)
    if not owner.user_id and not owner.device_fp:
        raise HTTPException(status_code=400, detail="缺少设备标识")

    proj = await project_manager.get_project(project_id)
    if not proj or not _owns_project(proj, owner):
        raise HTTPException(status_code=404, detail="项目不存在")

    if req.plan_content is not None:
        await project_manager.write_project_md(project_id, req.plan_content)

        state = build_orchestrator.get_build_state(project_id)
        if state:
            state.plan_content = req.plan_content

    return {"success": True}


@router.get("/{project_id}")
async def get_build_project(project_id: str, request: Request):
    """Get project status and plan content."""
    owner = await get_owner_context(request)
    if not owner.user_id and not owner.device_fp:
        raise HTTPException(status_code=400, detail="缺少设备标识")

    proj = await project_manager.get_project(project_id)
    if not proj or not _owns_project(proj, owner):
        raise HTTPException(status_code=404, detail="项目不存在")

    plan_content = await project_manager.read_project_md(project_id)

    return {
        **proj,
        "plan_content": plan_content,
    }


@router.get("")
async def list_build_projects(request: Request, limit: int = 20):
    """List build projects for the current user/device."""
    owner = await get_owner_context(request)
    if not owner.user_id and not owner.device_fp:
        raise HTTPException(status_code=400, detail="缺少设备标识")

    projects = await project_manager.list_projects(owner.device_fp, limit)
    return {"projects": projects}


@router.delete("/{project_id}")
async def delete_build_project(project_id: str, request: Request):
    """Delete a build project."""
    owner = await get_owner_context(request)
    if not owner.user_id and not owner.device_fp:
        raise HTTPException(status_code=400, detail="缺少设备标识")

    proj = await project_manager.get_project(project_id)
    if not proj or not _owns_project(proj, owner):
        raise HTTPException(status_code=404, detail="项目不存在")

    await project_manager.delete_project(project_id)
    return {"success": True}
