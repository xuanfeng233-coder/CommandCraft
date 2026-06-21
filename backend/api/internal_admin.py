"""Internal admin endpoints — called by BraynLabs's admin panel.

Authorization: shared-secret header (`X-Internal-Token`) checked against
`INTERNAL_ADMIN_TOKEN`. The user-facing auth boundary lives in BraynLabs;
this token only authorizes BraynLabs-the-process to call us.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException

from backend.config import INTERNAL_ADMIN_TOKEN
from backend.subscription.database import subscription_db

logger = logging.getLogger(__name__)


def _verify_token(x_internal_token: str | None = Header(default=None)) -> None:
    if not INTERNAL_ADMIN_TOKEN:
        raise HTTPException(503, "INTERNAL_ADMIN_TOKEN not configured")
    if not x_internal_token or not secrets.compare_digest(
        x_internal_token, INTERNAL_ADMIN_TOKEN
    ):
        raise HTTPException(401, "Invalid internal token")


router = APIRouter(
    prefix="/api/internal/admin",
    tags=["internal-admin"],
    dependencies=[Depends(_verify_token)],
)


@router.get("/stats")
async def get_stats() -> Any:
    return await subscription_db.get_stats()


@router.post("/cleanup-expired")
async def cleanup_expired() -> Any:
    return await subscription_db.cleanup_expired()


@router.get("/devices")
async def list_devices() -> Any:
    return await subscription_db.get_all_devices()


@router.get("/devices/{device_fp}")
async def get_device(device_fp: str) -> Any:
    detail = await subscription_db.get_device_detail(device_fp)
    if not detail["subscriptions"]:
        raise HTTPException(404, "Device not found")
    return detail


@router.get("/usage/history")
async def usage_history(days: int = 30) -> Any:
    raw = await subscription_db.get_all_usage_history(days=days)
    by_device: dict[str, list[dict[str, Any]]] = {}
    for row in raw:
        fp = row["device_fp"]
        by_device.setdefault(fp, []).append({"date": row["date"], "count": row["call_count"]})
    return by_device


@router.get("/usage/history/{device_fp}")
async def device_usage_history(device_fp: str, days: int = 30) -> Any:
    return await subscription_db.get_usage_history(device_fp, days=days)


@router.get("/orders")
async def list_orders(
    user_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
) -> Any:
    """List WXpay orders for support/refund workflows."""
    return await subscription_db.list_wxpay_orders(
        user_id=user_id, status=status, limit=limit
    )


@router.get("/devices/{device_fp}/export")
async def export_device(device_fp: str) -> Any:
    """Dump everything we hold for one device."""
    detail = await subscription_db.get_device_detail(device_fp)
    if not detail.get("subscriptions"):
        raise HTTPException(404, "Device not found")
    usage_30d = await subscription_db.get_usage_history(device_fp, days=30)
    usage_365d = await subscription_db.get_usage_history(device_fp, days=365)
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "device_fp": device_fp,
        "detail": detail,
        "usage_history_30d": usage_30d,
        "usage_history_365d": usage_365d,
    }
