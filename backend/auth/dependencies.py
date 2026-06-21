"""FastAPI dependencies for authentication and owner context."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request

from backend.auth.database import auth_db


@dataclass
class OwnerContext:
    """Unified identity: logged-in user (user_id) or anonymous device (device_fp)."""

    user_id: int | None = None
    device_fp: str = ""

    @property
    def is_logged_in(self) -> bool:
        return self.user_id is not None

    def session_filter(self) -> tuple[str, list]:
        """Return (WHERE clause, params) for filtering sessions/subscriptions."""
        if self.user_id is not None:
            return "user_id = ?", [self.user_id]
        return "device_fp = ? AND user_id IS NULL", [self.device_fp]

    def log_id(self) -> str:
        """Short identifier for logging."""
        if self.user_id is not None:
            return f"user:{self.user_id}"
        return self.device_fp[:8] if self.device_fp else "anon"


async def get_current_user(request: Request) -> dict | None:
    """Read auth_token cookie and validate. Returns {user_id, username} or None."""
    token = request.cookies.get("auth_token")
    if not token:
        return None
    return await auth_db.validate_token(token)


async def require_user(request: Request) -> dict:
    """Like get_current_user but raises 401 if not logged in."""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


async def get_owner_context(request: Request) -> OwnerContext:
    """Build unified OwnerContext from cookie (preferred) or X-Device-Fp header."""
    user = await get_current_user(request)
    device_fp = request.headers.get("X-Device-Fp", "")
    if user:
        return OwnerContext(user_id=user["user_id"], device_fp=device_fp)
    return OwnerContext(device_fp=device_fp)
