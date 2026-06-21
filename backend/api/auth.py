"""Authentication API: SSO callback (via BraynLabs) + device management.

Users authenticate on BraynLabs and are redirected back with an SSO ticket.
This module exchanges the ticket for user info and creates a local session.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from backend.auth.database import auth_db
from backend.auth.dependencies import get_current_user, require_user
from backend.config import (
    AUTH_COOKIE_SECURE,
    AUTH_MAX_DEVICES,
    AUTH_SESSION_TTL_DAYS,
    BRAYNLABS_URL,
    SSO_CLIENT_ID,
    SSO_CLIENT_SECRET,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _get_client_ip(request: Request) -> str:
    return request.headers.get("X-Real-IP") or (
        request.client.host if request.client else "unknown"
    )


def _set_auth_cookie(response: JSONResponse | RedirectResponse, token: str) -> None:
    response.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        secure=AUTH_COOKIE_SECURE,
        samesite="lax",
        path="/api",
        max_age=AUTH_SESSION_TTL_DAYS * 86400,
    )


def _clear_auth_cookie(response: JSONResponse) -> None:
    response.delete_cookie(key="auth_token", path="/api")


async def _migrate_device_data(user_id: int, device_fp: str) -> dict[str, int]:
    """Migrate device_fp data to user account. Returns migration counts."""
    if not device_fp:
        return {}
    counts: dict[str, int] = {}

    # Migrate chat sessions (sessions.db)
    from backend.models.database import session_db

    cursor = await session_db.db.execute(
        "UPDATE sessions SET user_id = ? WHERE device_fp = ? AND user_id IS NULL",
        (user_id, device_fp),
    )
    await session_db.db.commit()
    counts["sessions"] = cursor.rowcount

    # Migrate subscription data (subscriptions.db — same db as auth)
    db = auth_db.db
    for table in ("subscriptions", "usage", "build_usage"):
        try:
            cursor = await db.execute(
                f"UPDATE {table} SET user_id = ? WHERE device_fp = ? AND user_id IS NULL",
                (user_id, device_fp),
            )
            counts[table] = cursor.rowcount
        except Exception:
            pass
    await db.commit()

    total = sum(counts.values())
    if total > 0:
        logger.info("Migrated device data for user %d (fp=%s): %s", user_id, device_fp[:8], counts)
    return counts


# --- SSO callback ---


@router.get("/sso/callback")
async def sso_callback(ticket: str, request: Request, redirect: str | None = None):
    """Receive SSO ticket from BraynLabs redirect, exchange for user info, create local session."""
    # Exchange ticket with BraynLabs server-to-server
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BRAYNLABS_URL}/api/auth/sso/exchange",
                json={
                    "ticket": ticket,
                    "client_id": SSO_CLIENT_ID,
                    "client_secret": SSO_CLIENT_SECRET,
                },
            )
    except httpx.HTTPError as e:
        logger.error("SSO exchange request failed: %s", e)
        return RedirectResponse(url="/?sso_error=network", status_code=302)

    if resp.status_code != 200:
        logger.warning("SSO exchange returned %d: %s", resp.status_code, resp.text[:200])
        return RedirectResponse(url="/?sso_error=invalid_ticket", status_code=302)

    data = resp.json()
    user_info = data.get("user")
    if not user_info or not user_info.get("id"):
        return RedirectResponse(url="/?sso_error=invalid_response", status_code=302)

    braynlabs_id = user_info["id"]
    username = user_info["username"]
    email = user_info.get("email")

    # Upsert local SSO user cache
    await auth_db.upsert_sso_user(braynlabs_id, username, email)

    # Reuse existing session if available (BraynLabs login already created one
    # in the shared DB — creating another would double-count the device).
    user_agent = request.headers.get("User-Agent", "")
    existing = await auth_db.find_reusable_session(braynlabs_id, user_agent[:200])
    if existing:
        token = existing
    else:
        # Check device limit only when creating a new session
        active_count = await auth_db.count_active_sessions(braynlabs_id)
        if active_count >= AUTH_MAX_DEVICES:
            return RedirectResponse(url="/?sso_error=device_limit", status_code=302)

        device_fp = request.headers.get("X-Device-Fp", "")
        client_ip = _get_client_ip(request)
        token = await auth_db.create_auth_session(
            user_id=braynlabs_id,
            device_fp=device_fp,
            user_agent=user_agent[:200],
            ip_addr=client_ip,
        )

        # Migrate anonymous device data
        await _migrate_device_data(braynlabs_id, device_fp)

    # Redirect back to peer site if provided, otherwise stay on CommandCraft
    target = "/"
    if redirect:
        from urllib.parse import urlparse
        parsed = urlparse(redirect)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin == BRAYNLABS_URL:
            target = redirect

    response = RedirectResponse(url=target, status_code=302)
    _set_auth_cookie(response, token)
    return response


# --- Session management ---


@router.post("/logout")
async def logout(request: Request):
    token = request.cookies.get("auth_token")
    if token:
        await auth_db.delete_auth_session(token)
    response = JSONResponse(content={"success": True})
    _clear_auth_cookie(response)
    return response


@router.get("/me")
async def me(request: Request):
    user = await get_current_user(request)
    if not user:
        return {"user": None}
    return {"user": user}


# --- Device management ---


class KickRequest(BaseModel):
    token: str


@router.get("/devices")
async def list_devices(request: Request):
    user = await require_user(request)
    devices = await auth_db.list_active_sessions(user["user_id"])
    current_token = request.cookies.get("auth_token", "")
    return {
        "devices": [
            {
                "token": d["token"],
                "user_agent": d["user_agent"][:100],
                "ip_addr": d["ip_addr"],
                "created_at": d["created_at"],
                "last_active_at": d["last_active_at"],
                "is_current": d["token"] == current_token,
            }
            for d in devices
        ]
    }


@router.post("/kick")
async def kick_device(req: KickRequest, request: Request):
    user = await require_user(request)
    devices = await auth_db.list_active_sessions(user["user_id"])
    if not any(d["token"] == req.token for d in devices):
        raise HTTPException(status_code=404, detail="设备不存在")
    await auth_db.delete_auth_session(req.token)
    return {"success": True}
