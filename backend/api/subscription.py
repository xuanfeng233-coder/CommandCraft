"""Subscription API endpoints — WXpay-driven activation."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from backend.auth.dependencies import get_owner_context, require_user
from backend.config import (
    WXPAY_CALLBACK_URL,
    WXPAY_ENABLED,
    WXPAY_ORDER_TTL_SECONDS,
    WXPAY_WEBHOOK_SECRET,
)
from backend.subscription.database import subscription_db
from backend.subscription.plans import PLANS
from backend.subscription.wxpay_client import (
    WxpayRateLimited,
    WxpayUnavailable,
    get_wxpay_client,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/subscription", tags=["subscription"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TERMINAL_STATUSES = {"paid", "amount_mismatch", "expired", "cancelled"}
_QR_IMAGE_URL = "/images/payment.png"


def _is_pending(status: str) -> bool:
    return status not in _TERMINAL_STATUSES


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _sync_order_from_wxpay(order_id: str, local: dict) -> dict:
    """If local order is still pending and stale (>15s), pull fresh status
    from WXpay and persist. Returns the (possibly updated) local row."""
    if not _is_pending(local["status"]):
        return local

    last_synced = local.get("last_synced_at") or local["created_at"]
    try:
        last_dt = datetime.fromisoformat(last_synced)
    except ValueError:
        last_dt = datetime.now(timezone.utc)
    age = (datetime.now(timezone.utc) - last_dt).total_seconds()
    if age < 15:
        return local

    try:
        client = get_wxpay_client()
    except RuntimeError:
        return local

    try:
        remote = await client.get_order(order_id)
    except (WxpayUnavailable, WxpayRateLimited) as e:
        logger.warning("WXpay get_order(%s) failed during sync: %s", order_id, e)
        # Touch last_synced to avoid hammering the upstream.
        await subscription_db.touch_wxpay_order_synced(order_id)
        return local

    if not remote:
        await subscription_db.touch_wxpay_order_synced(order_id)
        return local

    new_status = remote.get("status", local["status"])
    if new_status != local["status"] or _is_pending(local["status"]):
        await subscription_db.update_wxpay_order_status(
            order_id=order_id,
            status=new_status,
            paid_at=remote.get("paid_at"),
            amount_diff_kind=remote.get("amount_diff_kind"),
            raw_payload=json.dumps(remote, ensure_ascii=False),
        )
        # Activate if eligible.
        if new_status in ("paid", "amount_mismatch"):
            await subscription_db.try_activate_wxpay_order(order_id)

    refreshed = await subscription_db.get_wxpay_order(order_id)
    return refreshed or local


def _serialize_order(row: dict, *, remote_extras: dict | None = None) -> dict:
    """Shape the order row for the frontend. Pulls actual_amount / amount_diff
    from raw_payload (last sync) when available."""
    extras = remote_extras or {}
    raw = row.get("raw_payload")
    if raw and not extras:
        try:
            extras = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            extras = {}

    payment_remark_hint = f"请在付款备注中输入: {row['order_id']}"
    return {
        "order_id": row["order_id"],
        "status": row["status"],
        "plan": row["plan"],
        "amount": row["amount_cny"],
        "actual_amount": extras.get("actual_amount"),
        "amount_diff": extras.get("amount_diff"),
        "amount_diff_kind": row.get("amount_diff_kind"),
        "expires_at": row["expires_at"],
        "paid_at": row.get("paid_at"),
        "created_at": row["created_at"],
        "activated": bool(row.get("activated")),
        "subscription_id": row.get("subscription_id"),
        "payment_remark_hint": payment_remark_hint,
        "qr_image_url": _QR_IMAGE_URL,
    }


# ---------------------------------------------------------------------------
# Status / plans
# ---------------------------------------------------------------------------


@router.get("/status")
async def get_status(request: Request, device_fp: str = ""):
    """Get subscription status for current user or device."""
    owner = await get_owner_context(request)
    fp = owner.device_fp or device_fp
    uid = owner.user_id

    effective = await subscription_db.get_effective_plan(device_fp=fp, user_id=uid)
    usage = await subscription_db.get_usage(device_fp=fp, user_id=uid)
    subscriptions = await subscription_db.get_all_subscriptions(device_fp=fp, user_id=uid)

    build_usage = 0
    build_limit = 0
    if effective:
        build_usage = await subscription_db.get_build_usage(device_fp=fp, user_id=uid)
        plan_key = effective.get("plan", "")
        plan_info = PLANS.get(plan_key)
        if plan_info:
            build_limit = plan_info.build_monthly

    return {
        "active": effective is not None,
        "plan": effective,
        "usage": usage,
        "build_usage": build_usage,
        "build_limit": build_limit,
        "subscriptions": subscriptions,
    }


@router.get("/plans")
async def get_plans():
    """Return available plan definitions."""
    return {
        "plans": [
            {
                "id": plan_id,
                "name": plan.name,
                "daily_limit": plan.daily,
                "monthly_limit": plan.monthly,
                "build_monthly": plan.build_monthly,
                "price_cny": plan.price_cny,
                "duration_days": plan.duration_days,
            }
            for plan_id, plan in PLANS.items()
        ]
    }


# ---------------------------------------------------------------------------
# WXpay orders
# ---------------------------------------------------------------------------


class CreateOrderRequest(BaseModel):
    plan_id: str
    device_fp: str = ""


@router.post("/orders")
async def create_order(req: CreateOrderRequest, request: Request):
    """Create a WXpay order for the current user. Requires login."""
    if not WXPAY_ENABLED:
        raise HTTPException(503, "微信支付未启用")

    user = await require_user(request)
    plan_id = req.plan_id.strip().lower()
    if plan_id not in PLANS:
        raise HTTPException(400, f"未知套餐: {plan_id}")

    plan = PLANS[plan_id]
    if not plan.price_cny or plan.price_cny == "0.00":
        raise HTTPException(400, "该套餐未配置价格")

    client = get_wxpay_client()

    # Health precheck — bail early if the bridge isn't actively listening,
    # so the user doesn't pay against a dead order.
    try:
        health = await client.healthz()
    except (WxpayUnavailable, WxpayRateLimited) as e:
        logger.warning("WXpay healthz failed: %s", e)
        raise HTTPException(503, "微信支付服务暂时不可用，请稍后再试") from e
    if not health.get("ok") or not health.get("polling_enabled"):
        raise HTTPException(503, "微信收款监听未启动，请稍后再试")

    metadata = {
        "user_id": user["user_id"],
        "plan_id": plan_id,
        "site": "commandcraft",
    }
    try:
        remote = await client.create_order(
            amount_cny=plan.price_cny,
            ttl_seconds=WXPAY_ORDER_TTL_SECONDS,
            callback_url=WXPAY_CALLBACK_URL or None,
            metadata=metadata,
        )
    except WxpayRateLimited as e:
        raise HTTPException(429, "请求过于频繁，请稍后再试") from e
    except WxpayUnavailable as e:
        logger.error("WXpay create_order failed: %s", e)
        raise HTTPException(503, "微信支付服务暂时不可用，请稍后再试") from e

    order_id = remote.get("order_id")
    expires_at = remote.get("expires_at")
    if not order_id or not expires_at:
        raise HTTPException(502, "微信支付返回数据异常")

    await subscription_db.create_wxpay_order(
        order_id=order_id,
        user_id=user["user_id"],
        device_fp=req.device_fp.strip(),
        plan=plan_id,
        amount_cny=plan.price_cny,
        expires_at=expires_at,
    )

    return {
        "order_id": order_id,
        "status": "pending",
        "plan": plan_id,
        "plan_name": plan.name,
        "amount": plan.price_cny,
        "expires_at": expires_at,
        "payment_remark_hint": remote.get("payment_remark_hint")
            or f"请在付款备注中输入: {order_id}",
        "qr_image_url": _QR_IMAGE_URL,
    }


@router.get("/orders/{order_id}")
async def get_order(order_id: str, request: Request):
    """Poll an order. Owner-only. Auto-syncs from WXpay if pending+stale."""
    user = await require_user(request)
    local = await subscription_db.get_wxpay_order(order_id)
    if not local:
        raise HTTPException(404, "订单不存在")
    if local["user_id"] != user["user_id"]:
        raise HTTPException(403, "无权访问该订单")

    local = await _sync_order_from_wxpay(order_id, local)
    return _serialize_order(local)


@router.delete("/orders/{order_id}")
async def cancel_order(order_id: str, request: Request):
    """Cancel a pending order. Owner-only."""
    user = await require_user(request)
    local = await subscription_db.get_wxpay_order(order_id)
    if not local:
        raise HTTPException(404, "订单不存在")
    if local["user_id"] != user["user_id"]:
        raise HTTPException(403, "无权访问该订单")
    if not _is_pending(local["status"]):
        raise HTTPException(409, f"订单已是终态: {local['status']}")

    try:
        client = get_wxpay_client()
        await client.cancel_order(order_id)
    except (WxpayUnavailable, WxpayRateLimited) as e:
        logger.warning("WXpay cancel_order(%s) failed: %s", order_id, e)
        # Still mark locally cancelled — user-facing intent is honored.

    await subscription_db.update_wxpay_order_status(
        order_id=order_id,
        status="cancelled",
        paid_at=None,
        amount_diff_kind=local.get("amount_diff_kind"),
        raw_payload=None,
    )
    refreshed = await subscription_db.get_wxpay_order(order_id) or local
    return _serialize_order(refreshed)


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------


@router.post("/wxpay/webhook")
async def wxpay_webhook(
    request: Request,
    x_wxpay_signature: str = Header(default=""),
    x_wxpay_order_id: str = Header(default=""),
):
    """Receive a payment notification from the WXpay bridge.

    Signature is HMAC-SHA256(WXPAY_WEBHOOK_SECRET, raw_body) hex. We must read
    the raw body BEFORE parsing JSON to verify the signature byte-exact.
    """
    if not WXPAY_WEBHOOK_SECRET:
        # Misconfiguration — refuse rather than silently accept.
        raise HTTPException(503, "Webhook secret not configured")

    body = await request.body()
    expected = hmac.new(
        WXPAY_WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, x_wxpay_signature):
        logger.warning(
            "WXpay webhook signature mismatch (order_id=%s)", x_wxpay_order_id
        )
        raise HTTPException(401, "Invalid signature")

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON body") from None

    order_id = event.get("order_id")
    if not order_id:
        raise HTTPException(400, "Missing order_id")

    local = await subscription_db.get_wxpay_order(order_id)
    if not local:
        # Not our order — ack so WXpay stops retrying.
        logger.info("WXpay webhook for unknown order %s — ignoring", order_id)
        return {"ok": True, "ignored": True}

    status = event.get("status", local["status"])
    await subscription_db.update_wxpay_order_status(
        order_id=order_id,
        status=status,
        paid_at=event.get("occurred_at"),
        amount_diff_kind=event.get("amount_diff_kind"),
        raw_payload=body.decode("utf-8", errors="replace"),
    )

    activated_sub = None
    if status in ("paid", "amount_mismatch"):
        activated_sub = await subscription_db.try_activate_wxpay_order(order_id)

    return {
        "ok": True,
        "order_id": order_id,
        "status": status,
        "activated": activated_sub is not None,
    }
