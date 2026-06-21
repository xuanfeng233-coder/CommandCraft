"""SQLite storage for subscriptions, WXpay orders, and usage tracking."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from backend.config import SUBSCRIPTION_DB_PATH
from backend.subscription.plans import PLANS

logger = logging.getLogger(__name__)


_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_fp TEXT NOT NULL,
    user_id INTEGER,
    plan TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    code TEXT,
    source TEXT NOT NULL DEFAULT 'wxpay',
    order_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_subs_fp ON subscriptions(device_fp);
CREATE INDEX IF NOT EXISTS idx_subs_user ON subscriptions(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_subs_order_id
    ON subscriptions(order_id) WHERE order_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS usage (
    device_fp TEXT NOT NULL,
    user_id INTEGER DEFAULT NULL,
    date TEXT NOT NULL,
    call_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (device_fp, date)
);

CREATE TABLE IF NOT EXISTS build_usage (
    device_fp TEXT NOT NULL,
    user_id INTEGER DEFAULT NULL,
    month TEXT NOT NULL,
    build_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (device_fp, month)
);

CREATE TABLE IF NOT EXISTS wxpay_orders (
    order_id        TEXT PRIMARY KEY,
    user_id         INTEGER NOT NULL,
    device_fp       TEXT NOT NULL DEFAULT '',
    plan            TEXT NOT NULL,
    amount_cny      TEXT NOT NULL,
    status          TEXT NOT NULL,
    amount_diff_kind TEXT,
    activated       INTEGER NOT NULL DEFAULT 0,
    subscription_id INTEGER,
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    paid_at         TEXT,
    last_synced_at  TEXT NOT NULL,
    raw_payload     TEXT
);

CREATE INDEX IF NOT EXISTS idx_orders_user ON wxpay_orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON wxpay_orders(status);
"""


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
        # Foreign keys intentionally NOT enabled — old `code` FK to dropped `codes` table
        # would break legacy rows during the rebuild migration below.

        # Migrate legacy schema before creating tables. This handles instances
        # that already have the old `codes` table + `subscriptions.code NOT NULL`.
        await self._migrate_legacy_subscriptions()
        await self._migrate_drop_codes_table()

        await self._db.executescript(_CREATE_TABLES)
        await self._db.commit()

        # Migrate: add user_id columns for older usage/build_usage tables (idempotent).
        for table in ("usage", "build_usage"):
            try:
                await self._db.execute(
                    f"ALTER TABLE {table} ADD COLUMN user_id INTEGER DEFAULT NULL"
                )
                await self._db.commit()
            except Exception:
                pass

    async def _migrate_legacy_subscriptions(self) -> None:
        """Rebuild `subscriptions` if it lacks the `source` column.

        Old schema: `code TEXT NOT NULL` + FK to `codes`.
        New schema: `code TEXT` (nullable, no FK) + `source` + `order_id`.
        SQLite can't drop NOT NULL or FKs in place, so we rebuild via a
        temp table when the migration hasn't run yet.
        """
        cursor = await self._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='subscriptions'"
        )
        if not await cursor.fetchone():
            return  # fresh install — nothing to migrate, _CREATE_TABLES handles it

        cursor = await self._db.execute("PRAGMA table_info(subscriptions)")
        cols = {row["name"] for row in await cursor.fetchall()}
        if "source" in cols:
            return  # already migrated
        has_user_id = "user_id" in cols

        logger.info("Migrating subscriptions table to new schema (source/order_id)")
        user_id_select = "user_id" if has_user_id else "NULL"
        await self._db.executescript(
            f"""
            BEGIN;
            CREATE TABLE subscriptions_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_fp TEXT NOT NULL,
                user_id INTEGER,
                plan TEXT NOT NULL,
                starts_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                code TEXT,
                source TEXT NOT NULL DEFAULT 'wxpay',
                order_id TEXT
            );
            INSERT INTO subscriptions_new (id, device_fp, user_id, plan, starts_at, expires_at, code, source)
                SELECT id, device_fp, {user_id_select}, plan, starts_at, expires_at, code, 'code'
                FROM subscriptions;
            DROP TABLE subscriptions;
            ALTER TABLE subscriptions_new RENAME TO subscriptions;
            COMMIT;
            """
        )

    async def _migrate_drop_codes_table(self) -> None:
        """Remove the legacy `codes` table if it still exists."""
        cursor = await self._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='codes'"
        )
        if not await cursor.fetchone():
            return
        logger.info("Dropping legacy `codes` table (subscription codes retired)")
        await self._db.execute("DROP TABLE codes")
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "SubscriptionDB not initialized. Call init() first."
        return self._db

    # --- Stats ---

    async def get_stats(self) -> dict[str, Any]:
        """Get subscription statistics by plan."""
        stats: dict[str, Any] = {}
        now = _now_iso()
        for plan_key in PLANS:
            cursor = await self.db.execute(
                "SELECT COUNT(*) as total FROM subscriptions WHERE plan = ?",
                (plan_key,),
            )
            total = (await cursor.fetchone())["total"]
            cursor = await self.db.execute(
                "SELECT COUNT(*) as active FROM subscriptions WHERE plan = ? AND expires_at > ?",
                (plan_key, now),
            )
            active = (await cursor.fetchone())["active"]
            stats[plan_key] = {"total": total, "active": active}

        cursor = await self.db.execute(
            "SELECT COUNT(DISTINCT device_fp) as active FROM subscriptions WHERE expires_at > ?",
            (now,),
        )
        stats["active_devices"] = (await cursor.fetchone())["active"]
        return stats

    # --- Subscription creation (shared by WXpay activation) ---

    async def _create_subscription(
        self,
        *,
        plan: str,
        user_id: int | None,
        device_fp: str,
        source: str,
        order_id: str | None = None,
    ) -> dict[str, Any]:
        """Insert a subscription row with stacking semantics.

        Stacking: same plan + same owner extends from latest expiry; different
        plans are independent (priority ranking decides which one is "effective"
        at runtime).
        """
        plan_info = PLANS[plan]
        now = _now_utc()

        if user_id is not None:
            cursor = await self.db.execute(
                "SELECT MAX(expires_at) as latest FROM subscriptions WHERE user_id = ? AND plan = ?",
                (user_id, plan),
            )
        else:
            cursor = await self.db.execute(
                "SELECT MAX(expires_at) as latest FROM subscriptions WHERE device_fp = ? AND plan = ?",
                (device_fp, plan),
            )
        row = await cursor.fetchone()
        latest_expiry_str = row["latest"] if row else None

        if latest_expiry_str:
            latest_expiry = datetime.fromisoformat(latest_expiry_str)
            starts_at = latest_expiry if latest_expiry > now else now
        else:
            starts_at = now

        expires_at = starts_at + timedelta(days=plan_info.duration_days)

        cursor = await self.db.execute(
            """INSERT INTO subscriptions
               (device_fp, user_id, plan, starts_at, expires_at, code, source, order_id)
               VALUES (?, ?, ?, ?, ?, NULL, ?, ?)""",
            (
                device_fp,
                user_id,
                plan,
                starts_at.isoformat(),
                expires_at.isoformat(),
                source,
                order_id,
            ),
        )
        sub_id = cursor.lastrowid
        await self.db.commit()

        return {
            "subscription_id": sub_id,
            "plan": plan,
            "plan_name": plan_info.name,
            "starts_at": starts_at.isoformat(),
            "expires_at": expires_at.isoformat(),
        }

    # --- Subscription status ---

    async def get_effective_plan(
        self, device_fp: str = "", user_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Get the highest-priority active plan for a user or device."""
        now = _now_iso()
        if user_id is not None:
            cursor = await self.db.execute(
                """SELECT plan, MAX(expires_at) as expires_at
                   FROM subscriptions
                   WHERE user_id = ? AND expires_at > ?
                   GROUP BY plan""",
                (user_id, now),
            )
        else:
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

    async def get_all_subscriptions(
        self, device_fp: str = "", user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        if user_id is not None:
            cursor = await self.db.execute(
                "SELECT * FROM subscriptions WHERE user_id = ? ORDER BY expires_at DESC",
                (user_id,),
            )
        else:
            cursor = await self.db.execute(
                "SELECT * FROM subscriptions WHERE device_fp = ? ORDER BY expires_at DESC",
                (device_fp,),
            )
        return [dict(r) for r in await cursor.fetchall()]

    # --- Usage tracking ---

    async def get_usage(
        self, device_fp: str = "", user_id: int | None = None,
    ) -> dict[str, int]:
        today = _now_utc().strftime("%Y-%m-%d")
        month_prefix = today[:7]

        if user_id is not None:
            cursor = await self.db.execute(
                "SELECT SUM(call_count) as cnt FROM usage WHERE user_id = ? AND date = ?",
                (user_id, today),
            )
            row = await cursor.fetchone()
            daily = row["cnt"] if row and row["cnt"] else 0
            cursor = await self.db.execute(
                "SELECT SUM(call_count) as total FROM usage WHERE user_id = ? AND date LIKE ?",
                (user_id, f"{month_prefix}%"),
            )
            row = await cursor.fetchone()
            monthly = row["total"] if row and row["total"] else 0
        else:
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

    async def check_limits(
        self, device_fp: str = "", user_id: int | None = None,
    ) -> dict[str, Any]:
        effective = await self.get_effective_plan(device_fp=device_fp, user_id=user_id)
        if not effective:
            return {"allowed": False, "reason": "no_subscription"}

        usage = await self.get_usage(device_fp=device_fp, user_id=user_id)

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

    async def increment_usage(
        self, device_fp: str = "", user_id: int | None = None,
    ) -> None:
        today = _now_utc().strftime("%Y-%m-%d")
        if user_id is not None:
            await self.db.execute(
                """INSERT INTO usage (device_fp, user_id, date, call_count)
                   VALUES (?, ?, ?, 1)
                   ON CONFLICT(device_fp, date) DO UPDATE SET call_count = call_count + 1""",
                (f"user:{user_id}", user_id, today),
            )
        else:
            await self.db.execute(
                """INSERT INTO usage (device_fp, date, call_count)
                   VALUES (?, ?, 1)
                   ON CONFLICT(device_fp, date) DO UPDATE SET call_count = call_count + 1""",
                (device_fp, today),
            )
        await self.db.commit()

    # --- Build usage tracking ---

    async def get_build_usage(
        self, device_fp: str = "", user_id: int | None = None,
    ) -> int:
        month = _now_utc().strftime("%Y-%m")
        if user_id is not None:
            cursor = await self.db.execute(
                "SELECT SUM(build_count) as cnt FROM build_usage WHERE user_id = ? AND month = ?",
                (user_id, month),
            )
            row = await cursor.fetchone()
            return row["cnt"] if row and row["cnt"] else 0
        cursor = await self.db.execute(
            "SELECT build_count FROM build_usage WHERE device_fp = ? AND month = ?",
            (device_fp, month),
        )
        row = await cursor.fetchone()
        return row["build_count"] if row else 0

    async def check_build_limits(
        self, device_fp: str = "", user_id: int | None = None,
    ) -> dict[str, Any]:
        effective = await self.get_effective_plan(device_fp=device_fp, user_id=user_id)
        if not effective:
            return {"allowed": False, "reason": "no_subscription"}

        plan_key = effective["plan"]
        plan_info = PLANS.get(plan_key)
        if not plan_info or plan_info.build_monthly <= 0:
            return {
                "allowed": False,
                "reason": "plan_no_build",
                "plan": plan_key,
                "build_used": 0,
                "build_limit": 0,
            }

        build_used = await self.get_build_usage(device_fp=device_fp, user_id=user_id)
        allowed = build_used < plan_info.build_monthly

        return {
            "allowed": allowed,
            "reason": "" if allowed else "build_limit",
            "plan": plan_key,
            "plan_name": plan_info.name,
            "build_used": build_used,
            "build_limit": plan_info.build_monthly,
        }

    async def increment_build_usage(
        self, device_fp: str = "", user_id: int | None = None,
    ) -> None:
        month = _now_utc().strftime("%Y-%m")
        if user_id is not None:
            await self.db.execute(
                """INSERT INTO build_usage (device_fp, user_id, month, build_count)
                   VALUES (?, ?, ?, 1)
                   ON CONFLICT(device_fp, month) DO UPDATE SET build_count = build_count + 1""",
                (f"user:{user_id}", user_id, month),
            )
        else:
            await self.db.execute(
                """INSERT INTO build_usage (device_fp, month, build_count)
                   VALUES (?, ?, 1)
                   ON CONFLICT(device_fp, month) DO UPDATE SET build_count = build_count + 1""",
                (device_fp, month),
            )
        await self.db.commit()

    # --- WXpay orders ---

    async def create_wxpay_order(
        self,
        *,
        order_id: str,
        user_id: int,
        device_fp: str,
        plan: str,
        amount_cny: str,
        expires_at: str,
    ) -> None:
        now = _now_iso()
        await self.db.execute(
            """INSERT INTO wxpay_orders
               (order_id, user_id, device_fp, plan, amount_cny, status,
                amount_diff_kind, activated, subscription_id,
                created_at, expires_at, paid_at, last_synced_at, raw_payload)
               VALUES (?, ?, ?, ?, ?, 'pending', NULL, 0, NULL, ?, ?, NULL, ?, NULL)""",
            (order_id, user_id, device_fp, plan, amount_cny, now, expires_at, now),
        )
        await self.db.commit()

    async def get_wxpay_order(self, order_id: str) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            "SELECT * FROM wxpay_orders WHERE order_id = ?", (order_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_wxpay_order_status(
        self,
        *,
        order_id: str,
        status: str,
        paid_at: str | None,
        amount_diff_kind: str | None,
        raw_payload: str | None,
    ) -> None:
        await self.db.execute(
            """UPDATE wxpay_orders
                  SET status = ?,
                      paid_at = COALESCE(?, paid_at),
                      amount_diff_kind = ?,
                      last_synced_at = ?,
                      raw_payload = COALESCE(?, raw_payload)
                WHERE order_id = ?""",
            (status, paid_at, amount_diff_kind, _now_iso(), raw_payload, order_id),
        )
        await self.db.commit()

    async def touch_wxpay_order_synced(self, order_id: str) -> None:
        await self.db.execute(
            "UPDATE wxpay_orders SET last_synced_at = ? WHERE order_id = ?",
            (_now_iso(), order_id),
        )
        await self.db.commit()

    async def try_activate_wxpay_order(self, order_id: str) -> dict[str, Any] | None:
        """Atomically claim + activate an order. Returns the new subscription
        on first success; returns None if order can't activate (already
        activated, status not eligible, etc).

        Activation rules:
          - status == 'paid'  → activate
          - status == 'amount_mismatch' AND amount_diff_kind == 'overpaid' → activate
          - status == 'amount_mismatch' AND amount_diff_kind == 'underpaid' → DO NOT activate
          - any other status → DO NOT activate

        The UPDATE...WHERE clause is the lock: aiosqlite serialises writes per
        connection, so concurrent webhook + poll will see exactly one rowcount==1
        winner. The loser returns None and the caller falls back to reading the
        existing subscription row.
        """
        cursor = await self.db.execute(
            """UPDATE wxpay_orders
                  SET activated = 1
                WHERE order_id = ?
                  AND activated = 0
                  AND ( status = 'paid'
                        OR (status = 'amount_mismatch' AND amount_diff_kind = 'overpaid') )""",
            (order_id,),
        )
        if cursor.rowcount == 0:
            await self.db.commit()
            return None

        order = await self.get_wxpay_order(order_id)
        if not order:
            await self.db.rollback()
            return None

        try:
            sub = await self._create_subscription(
                plan=order["plan"],
                user_id=order["user_id"],
                device_fp=order["device_fp"] or "",
                source="wxpay",
                order_id=order_id,
            )
        except Exception:
            # Roll back the activation flag so a retry can claim again.
            await self.db.execute(
                "UPDATE wxpay_orders SET activated = 0 WHERE order_id = ?",
                (order_id,),
            )
            await self.db.commit()
            raise

        await self.db.execute(
            "UPDATE wxpay_orders SET subscription_id = ? WHERE order_id = ?",
            (sub["subscription_id"], order_id),
        )
        await self.db.commit()
        return sub

    async def list_wxpay_orders(
        self, *, user_id: int | None = None, status: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        cursor = await self.db.execute(
            f"SELECT * FROM wxpay_orders {where} ORDER BY created_at DESC LIMIT ?",
            params,
        )
        return [dict(r) for r in await cursor.fetchall()]

    # --- Admin: cleanup ---

    async def cleanup_expired(self) -> dict[str, int]:
        """Remove expired subscriptions and orphaned usage records."""
        now = _now_iso()
        result: dict[str, int] = {}

        cursor = await self.db.execute(
            "DELETE FROM subscriptions WHERE expires_at <= ?", (now,)
        )
        result["subscriptions"] = cursor.rowcount

        cursor = await self.db.execute(
            """DELETE FROM usage WHERE device_fp NOT IN
               (SELECT DISTINCT device_fp FROM subscriptions)"""
        )
        result["usage"] = cursor.rowcount

        cursor = await self.db.execute(
            """DELETE FROM build_usage WHERE device_fp NOT IN
               (SELECT DISTINCT device_fp FROM subscriptions)"""
        )
        result["build_usage"] = cursor.rowcount

        await self.db.commit()
        return result

    # --- Admin: device & usage queries ---

    async def get_all_devices(self) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            """SELECT
                 s.device_fp,
                 GROUP_CONCAT(DISTINCT s.plan) AS plans,
                 MIN(s.starts_at) AS first_sub,
                 MAX(s.expires_at) AS latest_expiry,
                 COUNT(s.id) AS sub_count
               FROM subscriptions s
               GROUP BY s.device_fp
               ORDER BY latest_expiry DESC"""
        )
        rows = await cursor.fetchall()
        now = _now_iso()
        devices = []
        for r in rows:
            d = dict(r)
            d["active"] = d["latest_expiry"] > now if d["latest_expiry"] else False
            devices.append(d)
        return devices

    async def get_usage_history(
        self, device_fp: str, days: int = 30
    ) -> list[dict[str, Any]]:
        cutoff = (_now_utc() - timedelta(days=days)).strftime("%Y-%m-%d")
        cursor = await self.db.execute(
            """SELECT date, call_count FROM usage
               WHERE device_fp = ? AND date >= ?
               ORDER BY date ASC""",
            (device_fp, cutoff),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def get_all_usage_history(self, days: int = 30) -> list[dict[str, Any]]:
        cutoff = (_now_utc() - timedelta(days=days)).strftime("%Y-%m-%d")
        cursor = await self.db.execute(
            """SELECT device_fp, date, call_count FROM usage
               WHERE date >= ?
               ORDER BY date ASC, device_fp""",
            (cutoff,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def get_device_detail(self, device_fp: str) -> dict[str, Any]:
        subs = await self.get_all_subscriptions(device_fp)
        usage = await self.get_usage(device_fp)
        history = await self.get_usage_history(device_fp, days=90)
        build_used = await self.get_build_usage(device_fp)
        effective = await self.get_effective_plan(device_fp)

        return {
            "device_fp": device_fp,
            "effective_plan": effective,
            "subscriptions": subs,
            "usage": usage,
            "build_used": build_used,
            "usage_history": history,
        }


# Singleton
subscription_db = SubscriptionDB()
