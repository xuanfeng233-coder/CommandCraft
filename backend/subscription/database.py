"""SQLite storage for subscription codes, subscriptions, and usage tracking."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from backend.config import SUBSCRIPTION_DB_PATH
from backend.subscription.plans import PLANS

logger = logging.getLogger(__name__)

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS codes (
    code TEXT PRIMARY KEY,
    plan TEXT NOT NULL,
    created_at TEXT NOT NULL,
    redeemed_by TEXT DEFAULT NULL,
    redeemed_at TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_fp TEXT NOT NULL,
    plan TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    code TEXT NOT NULL,
    FOREIGN KEY (code) REFERENCES codes(code)
);

CREATE INDEX IF NOT EXISTS idx_subs_fp ON subscriptions(device_fp);

CREATE TABLE IF NOT EXISTS usage (
    device_fp TEXT NOT NULL,
    date TEXT NOT NULL,
    call_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (device_fp, date)
);
"""

SUBSCRIPTION_DAYS = 30


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class SubscriptionDB:
    """Async SQLite wrapper for subscription management."""

    def __init__(self, db_path: str | None = None):
        self._db_path = str(db_path or SUBSCRIPTION_DB_PATH)
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        SUBSCRIPTION_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.executescript(_CREATE_TABLES)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "SubscriptionDB not initialized. Call init() first."
        return self._db

    # --- Codes ---

    async def add_codes(self, codes: list[dict[str, str]]) -> int:
        """Batch insert codes. Each dict: {code, plan, created_at}."""
        await self.db.executemany(
            "INSERT INTO codes (code, plan, created_at) VALUES (?, ?, ?)",
            [(c["code"], c["plan"], c["created_at"]) for c in codes],
        )
        await self.db.commit()
        return len(codes)

    async def get_code(self, code: str) -> dict[str, Any] | None:
        cursor = await self.db.execute("SELECT * FROM codes WHERE code = ?", (code,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_codes(
        self, plan: str | None = None, redeemed: bool | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM codes WHERE 1=1"
        params: list[Any] = []
        if plan:
            query += " AND plan = ?"
            params.append(plan)
        if redeemed is True:
            query += " AND redeemed_by IS NOT NULL"
        elif redeemed is False:
            query += " AND redeemed_by IS NULL"
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = await self.db.execute(query, params)
        return [dict(r) for r in await cursor.fetchall()]

    async def get_stats(self) -> dict[str, Any]:
        """Get code/subscription statistics."""
        stats: dict[str, Any] = {}
        for plan_key in PLANS:
            cursor = await self.db.execute(
                "SELECT COUNT(*) as total FROM codes WHERE plan = ?", (plan_key,)
            )
            total = (await cursor.fetchone())["total"]
            cursor = await self.db.execute(
                "SELECT COUNT(*) as used FROM codes WHERE plan = ? AND redeemed_by IS NOT NULL",
                (plan_key,),
            )
            used = (await cursor.fetchone())["used"]
            stats[plan_key] = {"total": total, "used": used, "available": total - used}

        cursor = await self.db.execute(
            "SELECT COUNT(DISTINCT device_fp) as active FROM subscriptions WHERE expires_at > ?",
            (_now_iso(),),
        )
        stats["active_devices"] = (await cursor.fetchone())["active"]
        return stats

    # --- Redeem ---

    async def redeem_code(self, code: str, device_fp: str) -> dict[str, Any]:
        """Validate and redeem a code for a device.

        Stacking: same plan extends from latest expiry; different plans independent.
        Returns: {success, plan, starts_at, expires_at, message}
        """
        code_row = await self.get_code(code)
        if not code_row:
            return {"success": False, "message": "兑换码不存在"}
        if code_row["redeemed_by"]:
            return {"success": False, "message": "兑换码已被使用"}

        plan = code_row["plan"]
        if plan not in PLANS:
            return {"success": False, "message": "无效的套餐类型"}

        now = _now_utc()

        # Stacking: find latest expiry for same plan + same device
        cursor = await self.db.execute(
            "SELECT MAX(expires_at) as latest FROM subscriptions WHERE device_fp = ? AND plan = ?",
            (device_fp, plan),
        )
        row = await cursor.fetchone()
        latest_expiry_str = row["latest"] if row else None

        if latest_expiry_str:
            latest_expiry = datetime.fromisoformat(latest_expiry_str)
            if latest_expiry > now:
                # Extend from latest expiry
                starts_at = latest_expiry
            else:
                starts_at = now
        else:
            starts_at = now

        expires_at = starts_at + timedelta(days=SUBSCRIPTION_DAYS)

        # Mark code as redeemed
        await self.db.execute(
            "UPDATE codes SET redeemed_by = ?, redeemed_at = ? WHERE code = ?",
            (device_fp, _now_iso(), code),
        )

        # Create subscription
        await self.db.execute(
            "INSERT INTO subscriptions (device_fp, plan, starts_at, expires_at, code) VALUES (?, ?, ?, ?, ?)",
            (device_fp, plan, starts_at.isoformat(), expires_at.isoformat(), code),
        )
        await self.db.commit()

        plan_info = PLANS[plan]
        return {
            "success": True,
            "plan": plan,
            "plan_name": plan_info.name,
            "starts_at": starts_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "message": f"兑换成功！{plan_info.name} 套餐已激活，有效期至 {expires_at.strftime('%Y-%m-%d %H:%M')} UTC",
        }

    # --- Subscription status ---

    async def get_effective_plan(self, device_fp: str) -> dict[str, Any] | None:
        """Get the highest-priority active plan for a device."""
        now = _now_iso()
        cursor = await self.db.execute(
            """SELECT plan, MAX(expires_at) as expires_at
               FROM subscriptions
               WHERE device_fp = ? AND expires_at > ?
               GROUP BY plan""",
            (device_fp, now),
        )
        rows = await cursor.fetchall()
        if not rows:
            return None

        # Pick highest priority
        best: dict[str, Any] | None = None
        best_priority = -1
        for row in rows:
            plan_key = row["plan"]
            plan_info = PLANS.get(plan_key)
            if plan_info and plan_info.priority > best_priority:
                best_priority = plan_info.priority
                best = {
                    "plan": plan_key,
                    "plan_name": plan_info.name,
                    "daily_limit": plan_info.daily,
                    "monthly_limit": plan_info.monthly,
                    "expires_at": row["expires_at"],
                }
        return best

    async def get_all_subscriptions(self, device_fp: str) -> list[dict[str, Any]]:
        """Get all subscriptions for a device."""
        cursor = await self.db.execute(
            "SELECT * FROM subscriptions WHERE device_fp = ? ORDER BY expires_at DESC",
            (device_fp,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    # --- Usage tracking ---

    async def get_usage(self, device_fp: str) -> dict[str, int]:
        """Get daily and monthly usage for a device."""
        today = _now_utc().strftime("%Y-%m-%d")
        month_prefix = today[:7]  # YYYY-MM

        cursor = await self.db.execute(
            "SELECT call_count FROM usage WHERE device_fp = ? AND date = ?",
            (device_fp, today),
        )
        row = await cursor.fetchone()
        daily = row["call_count"] if row else 0

        cursor = await self.db.execute(
            "SELECT SUM(call_count) as total FROM usage WHERE device_fp = ? AND date LIKE ?",
            (device_fp, f"{month_prefix}%"),
        )
        row = await cursor.fetchone()
        monthly = row["total"] if row and row["total"] else 0

        return {"daily": daily, "monthly": monthly}

    async def check_limits(self, device_fp: str) -> dict[str, Any]:
        """Check if the device is within usage limits.

        Returns: {allowed, plan, plan_name, daily_used, daily_limit, monthly_used, monthly_limit}
        """
        effective = await self.get_effective_plan(device_fp)
        if not effective:
            return {"allowed": False, "reason": "no_subscription"}

        usage = await self.get_usage(device_fp)

        daily_used = usage["daily"]
        monthly_used = usage["monthly"]
        daily_limit = effective["daily_limit"]
        monthly_limit = effective["monthly_limit"]

        allowed = daily_used < daily_limit and monthly_used < monthly_limit
        reason = ""
        if not allowed:
            if daily_used >= daily_limit:
                reason = "daily_limit"
            else:
                reason = "monthly_limit"

        return {
            "allowed": allowed,
            "reason": reason,
            "plan": effective["plan"],
            "plan_name": effective["plan_name"],
            "daily_used": daily_used,
            "daily_limit": daily_limit,
            "monthly_used": monthly_used,
            "monthly_limit": monthly_limit,
            "expires_at": effective["expires_at"],
        }

    async def increment_usage(self, device_fp: str) -> None:
        """Increment today's usage count for a device (upsert)."""
        today = _now_utc().strftime("%Y-%m-%d")
        await self.db.execute(
            """INSERT INTO usage (device_fp, date, call_count)
               VALUES (?, ?, 1)
               ON CONFLICT(device_fp, date) DO UPDATE SET call_count = call_count + 1""",
            (device_fp, today),
        )
        await self.db.commit()


# Singleton
subscription_db = SubscriptionDB()
