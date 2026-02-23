"""Subscription plan definitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanLimits:
    name: str
    daily: int
    monthly: int
    priority: int  # higher = better plan


PLANS: dict[str, PlanLimits] = {
    "plus": PlanLimits(name="Plus", daily=20, monthly=500, priority=1),
    "pro": PlanLimits(name="Pro", daily=40, monthly=1000, priority=2),
    "ultra": PlanLimits(name="Ultra", daily=100, monthly=3000, priority=3),
}
