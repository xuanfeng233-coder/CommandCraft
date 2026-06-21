"""SQLite storage for SSO users and auth sessions.

Users authenticate via BraynLabs SSO. This module only stores cached user info
and local auth sessions — no passwords, no email verification.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from backend.config import (
    AUTH_SESSION_TTL_DAYS,
    SUBSCRIPTION_DB_PATH,
)

logger = logging.getLogger(__name__)

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS sso_users (
    braynlabs_id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    email TEXT DEFAULT NULL,
    synced_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    device_fp TEXT NOT NULL DEFAULT '',
    user_agent TEXT NOT NULL DEFAULT '',
    ip_addr TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_active_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES sso_users(braynlabs_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_auth_user ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_expires ON auth_sessions(expires_at);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class AuthDB:
    """Async SQLite wrapper for SSO-based authentication.

    Shares the same subscriptions.db file since auth and subscription data
    are closely related.
    """

    def __init__(self, db_path: str | None = None):
        self._db_path = str(db_path or SUBSCRIPTION_DB_PATH)
        self._db: aiosqlite.Connection | None = None

    async def init(self, db: aiosqlite.Connection | None = None) -> None:
        if db is not None:
            self._db = db
        else:
            SUBSCRIPTION_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._db = await aiosqlite.connect(self._db_path)
            self._db.row_factory = aiosqlite.Row
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.executescript(_CREATE_TABLES)
        await self._db.commit()

    async def close(self) -> None:
        pass

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "AuthDB not initialized. Call init() first."
        return self._db

    # --- SSO Users ---

    async def upsert_sso_user(
        self, braynlabs_id: int, username: str, email: str | None = None,
    ) -> None:
        now = _now_iso()
        await self.db.execute(
            """INSERT INTO sso_users (braynlabs_id, username, email, synced_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(braynlabs_id) DO UPDATE SET
                 username = excluded.username,
                 email = excluded.email,
                 synced_at = excluded.synced_at""",
            (braynlabs_id, username, email, now),
        )
        await self.db.commit()

    async def get_sso_user(self, braynlabs_id: int) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            "SELECT * FROM sso_users WHERE braynlabs_id = ?", (braynlabs_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    # --- Auth sessions ---

    async def create_auth_session(
        self,
        user_id: int,
        device_fp: str = "",
        user_agent: str = "",
        ip_addr: str = "",
    ) -> str:
        token = secrets.token_hex(32)
        now = _now_iso()
        expires = (_now_utc() + timedelta(days=AUTH_SESSION_TTL_DAYS)).isoformat()
        await self.db.execute(
            """INSERT INTO auth_sessions
               (token, user_id, device_fp, user_agent, ip_addr, created_at, expires_at, last_active_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (token, user_id, device_fp, user_agent, ip_addr, now, expires, now),
        )
        await self.db.commit()
        return token

    async def validate_token(self, token: str) -> dict[str, Any] | None:
        now = _now_iso()
        cursor = await self.db.execute(
            """SELECT a.user_id, u.username, u.email
               FROM auth_sessions a
               JOIN sso_users u ON a.user_id = u.braynlabs_id
               WHERE a.token = ? AND a.expires_at > ?""",
            (token, now),
        )
        row = await cursor.fetchone()
        if not row:
            return None

        user_id = row["user_id"]
        await self.db.execute(
            "UPDATE auth_sessions SET last_active_at = ? WHERE token = ?",
            (now, token),
        )
        await self.db.commit()
        return {
            "user_id": row["user_id"],
            "username": row["username"],
            "email": row["email"],
            "email_verified": True,
        }

    async def delete_auth_session(self, token: str) -> None:
        await self.db.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))
        await self.db.commit()

    async def find_reusable_session(self, user_id: int, user_agent: str) -> str | None:
        """Find an existing active session for the same user+UA (same device).

        Returns the token if found, so the SSO callback can reuse it
        instead of creating a duplicate session in the shared DB.
        """
        now = _now_iso()
        cursor = await self.db.execute(
            """SELECT token FROM auth_sessions
               WHERE user_id = ? AND user_agent = ? AND expires_at > ?
               ORDER BY last_active_at DESC LIMIT 1""",
            (user_id, user_agent, now),
        )
        row = await cursor.fetchone()
        if row:
            await self.db.execute(
                "UPDATE auth_sessions SET last_active_at = ? WHERE token = ?",
                (now, row["token"]),
            )
            await self.db.commit()
            return row["token"]
        return None

    async def count_active_sessions(self, user_id: int) -> int:
        now = _now_iso()
        cursor = await self.db.execute(
            "SELECT COUNT(*) as cnt FROM auth_sessions WHERE user_id = ? AND expires_at > ?",
            (user_id, now),
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def list_active_sessions(self, user_id: int) -> list[dict[str, Any]]:
        now = _now_iso()
        cursor = await self.db.execute(
            """SELECT token, device_fp, user_agent, ip_addr, created_at, last_active_at
               FROM auth_sessions
               WHERE user_id = ? AND expires_at > ?
               ORDER BY last_active_at DESC""",
            (user_id, now),
        )
        return [dict(r) for r in await cursor.fetchall()]

    # --- Cleanup ---

    async def cleanup_expired_sessions(self) -> int:
        now = _now_iso()
        cursor = await self.db.execute(
            "DELETE FROM auth_sessions WHERE expires_at <= ?", (now,)
        )
        await self.db.commit()
        return cursor.rowcount

    async def get_inactive_user_ids(self, days: int) -> list[int]:
        """Find users with no active sessions and no recent activity."""
        cutoff = (_now_utc() - timedelta(days=days)).isoformat()
        cursor = await self.db.execute(
            """SELECT u.braynlabs_id FROM sso_users u
               WHERE u.synced_at < ?
               AND NOT EXISTS (
                 SELECT 1 FROM auth_sessions a
                 WHERE a.user_id = u.braynlabs_id AND a.expires_at > ?
               )""",
            (cutoff, _now_iso()),
        )
        return [row["braynlabs_id"] for row in await cursor.fetchall()]

    async def cleanup_inactive_users(self, days: int) -> int:
        user_ids = await self.get_inactive_user_ids(days)
        if not user_ids:
            return 0
        placeholders = ",".join("?" for _ in user_ids)
        await self.db.execute(
            f"DELETE FROM sso_users WHERE braynlabs_id IN ({placeholders})", user_ids
        )
        # Clean subscription-related data
        for table in ("subscriptions", "usage", "build_usage"):
            try:
                await self.db.execute(
                    f"DELETE FROM {table} WHERE user_id IN ({placeholders})", user_ids
                )
            except Exception:
                pass
        await self.db.commit()
        logger.info("Cleaned up %d inactive SSO users", len(user_ids))
        return len(user_ids)


# Singleton
auth_db = AuthDB()
