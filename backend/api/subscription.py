"""Subscription API endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.subscription.database import subscription_db
from backend.subscription.plans import PLANS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/subscription", tags=["subscription"])


class RedeemRequest(BaseModel):
    code: str
    device_fp: str


@router.post("/redeem")
async def redeem_code(req: RedeemRequest):
    """Redeem a subscription code for a device."""
    code = req.code.strip().upper()
    device_fp = req.device_fp.strip()

    if not code:
        raise HTTPException(status_code=400, detail="兑换码不能为空")
    if not device_fp:
        raise HTTPException(status_code=400, detail="设备标识不能为空")

    result = await subscription_db.redeem_code(code, device_fp)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result


@router.get("/status")
async def get_status(device_fp: str):
    """Get subscription status for a device."""
    if not device_fp.strip():
        raise HTTPException(status_code=400, detail="设备标识不能为空")

    effective = await subscription_db.get_effective_plan(device_fp)
    usage = await subscription_db.get_usage(device_fp)
    subscriptions = await subscription_db.get_all_subscriptions(device_fp)

    return {
        "active": effective is not None,
        "plan": effective,
        "usage": usage,
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
            }
            for plan_id, plan in PLANS.items()
        ]
    }
