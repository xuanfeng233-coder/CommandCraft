"""SQLite session storage for chat history."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from backend.config import DATABASE_PATH

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    device_fp TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    msg_type TEXT DEFAULT NULL,
    command_json TEXT DEFAULT NULL,
    questions_json TEXT DEFAULT NULL,
    project_json TEXT DEFAULT NULL,
    thinking TEXT DEFAULT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionDB:
    """Async SQLite wrapper for session management."""

    def __init__(self, db_path: str | None = None):
        self._db_path = str(db_path or DATABASE_PATH)
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.executescript(_CREATE_TABLES)
        await self._db.commit()
        # Migrate: add project_json column if missing (for existing databases)
        try:
            await self._db.execute(
                "ALTER TABLE messages ADD COLUMN project_json TEXT DEFAULT NULL"
            )
            await self._db.commit()
        except Exception:
            pass  # Column already exists
        # Migrate: add device_fp column if missing
        try:
            await self._db.execute(
                "ALTER TABLE sessions ADD COLUMN device_fp TEXT NOT NULL DEFAULT ''"
            )
            await self._db.commit()
        except Exception:
            pass  # Column already exists
        # Migrate: add user_id column for account system
        try:
            await self._db.execute(
                "ALTER TABLE sessions ADD COLUMN user_id INTEGER DEFAULT NULL"
            )
            await self._db.commit()
        except Exception:
            pass
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)"
        )
        await self._db.commit()
        # Migrate: add edition column (bedrock/java)
        try:
            await self._db.execute(
                "ALTER TABLE sessions ADD COLUMN edition TEXT NOT NULL DEFAULT 'bedrock'"
            )
            await self._db.commit()
        except Exception:
            pass
        # Migrate: add mode column (chat/build)
        try:
            await self._db.execute(
                "ALTER TABLE sessions ADD COLUMN mode TEXT NOT NULL DEFAULT 'chat'"
            )
            await self._db.commit()
        except Exception:
            pass

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "Database not initialized. Call init() first."
        return self._db

    # --- Sessions ---

    async def create_session(
        self,
        title: str = "",
        device_fp: str = "",
        user_id: int | None = None,
        edition: str = "bedrock",
        mode: str = "chat",
    ) -> str:
        session_id = uuid.uuid4().hex[:12]
        now = _now_iso()
        await self.db.execute(
            "INSERT INTO sessions (id, title, device_fp, user_id, edition, mode, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, title, device_fp, user_id, edition, mode, now, now),
        )
        await self.db.commit()
        return session_id

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return dict(row)

    async def list_sessions(
        self,
        device_fp: str = "",
        limit: int = 50,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        if user_id is not None:
            cursor = await self.db.execute(
                "SELECT * FROM sessions WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
                (user_id, limit),
            )
        elif device_fp:
            cursor = await self.db.execute(
                "SELECT * FROM sessions WHERE device_fp = ? AND user_id IS NULL ORDER BY updated_at DESC LIMIT ?",
                (device_fp, limit),
            )
        else:
            cursor = await self.db.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def delete_session(
        self, session_id: str, device_fp: str = "", user_id: int | None = None,
    ) -> bool:
        if user_id is not None:
            cursor = await self.db.execute(
                "DELETE FROM sessions WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            )
        elif device_fp:
            cursor = await self.db.execute(
                "DELETE FROM sessions WHERE id = ? AND device_fp = ?",
                (session_id, device_fp),
            )
        else:
            cursor = await self.db.execute(
                "DELETE FROM sessions WHERE id = ?", (session_id,)
            )
        await self.db.commit()
        return cursor.rowcount > 0

    async def update_session_title(self, session_id: str, title: str) -> None:
        await self.db.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title, _now_iso(), session_id),
        )
        await self.db.commit()

    async def touch_session(self, session_id: str) -> None:
        await self.db.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (_now_iso(), session_id),
        )
        await self.db.commit()

    async def check_session_ownership(
        self, session_id: str, user_id: int | None, device_fp: str,
    ) -> bool:
        """Check if the session belongs to the given owner."""
        session = await self.get_session(session_id)
        if not session:
            return False
        if user_id is not None:
            return session.get("user_id") == user_id
        # Anonymous: match by device_fp
        return (
            not session.get("device_fp")
            or not device_fp
            or session["device_fp"] == device_fp
        )

    async def cleanup_by_user_ids(self, user_ids: list[int]) -> int:
        """Delete all sessions (and cascade messages) for given user_ids."""
        if not user_ids:
            return 0
        placeholders = ",".join("?" for _ in user_ids)
        cursor = await self.db.execute(
            f"DELETE FROM sessions WHERE user_id IN ({placeholders})", user_ids
        )
        await self.db.commit()
        return cursor.rowcount

    # --- Messages ---

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str = "",
        msg_type: str | None = None,
        command: dict | None = None,
        questions: list[dict] | None = None,
        project: dict | None = None,
        thinking: str | None = None,
    ) -> int:
        now = _now_iso()
        cursor = await self.db.execute(
            """INSERT INTO messages
               (session_id, role, content, msg_type, command_json, questions_json, project_json, thinking, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                role,
                content,
                msg_type,
                json.dumps(command, ensure_ascii=False) if command else None,
                json.dumps(questions, ensure_ascii=False) if questions else None,
                json.dumps(project, ensure_ascii=False) if project else None,
                thinking,
                now,
            ),
        )
        await self.db.commit()
        await self.touch_session(session_id)
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_messages(
        self, session_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC LIMIT ?",
            (session_id, limit),
        )
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            if d.get("command_json"):
                d["command"] = json.loads(d["command_json"])
            else:
                d["command"] = None
            if d.get("questions_json"):
                d["questions"] = json.loads(d["questions_json"])
            else:
                d["questions"] = None
            if d.get("project_json"):
                d["project"] = json.loads(d["project_json"])
            else:
                d["project"] = None
            del d["command_json"]
            del d["questions_json"]
            d.pop("project_json", None)
            result.append(d)
        return result

    async def get_recent_context(
        self, session_id: str, max_messages: int = 10
    ) -> str:
        """Build a conversation summary string from recent messages for Agent 1."""
        cursor = await self.db.execute(
            """SELECT role, content, msg_type FROM messages
               WHERE session_id = ? ORDER BY id DESC LIMIT ?""",
            (session_id, max_messages),
        )
        rows = await cursor.fetchall()
        if not rows:
            return ""
        # Reverse to chronological order
        rows = list(reversed(rows))
        parts = []
        for row in rows:
            role = "用户" if row["role"] == "user" else "AI"
            content = row["content"][:200] if row["content"] else ""
            if row["msg_type"] == "single_command":
                parts.append(f"{role}: [生成了命令] {content}")
            elif row["msg_type"] == "conversation":
                parts.append(f"{role}: [追问参数] {content}")
            else:
                parts.append(f"{role}: {content}")
        return "\n".join(parts)


# Singleton
session_db = SessionDB()
