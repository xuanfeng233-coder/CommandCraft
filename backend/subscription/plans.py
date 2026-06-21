"""Subscription plan definitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanLimits:
    name: str
    daily: int
    monthly: int
    priority: int  # higher = better plan
    build_monthly: int = 0  # monthly build mode quota (0 = disabled)
    price_cny: str = "0.00"  # price in CNY (Decimal-string, e.g. "29.00")
    duration_days: int = 30  # subscription length


PLANS: dict[str, PlanLimits] = {
    "plus":  PlanLimits(name="Plus",  daily=20,  monthly=500,  priority=1, build_monthly=0, price_cny="29.00", duration_days=30),
    "pro":   PlanLimits(name="Pro",   daily=40,  monthly=1000, priority=2, build_monthly=1, price_cny="59.00", duration_days=30),
    "ultra": PlanLimits(name="Ultra", daily=100, monthly=3000, priority=3, build_monthly=3, price_cny="99.00", duration_days=30),
}
