"""PROJECT.md file management + SQLite metadata for build projects."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from backend.config import BUILD_PROJECTS_DIR, SUBSCRIPTION_DB_PATH

logger = logging.getLogger(__name__)

_CREATE_BUILD_TABLES = """
CREATE TABLE IF NOT EXISTS build_projects (
    project_id TEXT PRIMARY KEY,
    device_fp TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'planning',
    step_index INTEGER NOT NULL DEFAULT 0,
    total_steps INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_build_fp ON build_projects(device_fp);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectManager:
    """Manages PROJECT.md files and SQLite metadata for build projects."""

    def __init__(self) -> None:
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        BUILD_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(SUBSCRIPTION_DB_PATH))
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_CREATE_BUILD_TABLES)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "ProjectManager not initialized"
        return self._db

    async def create_project(self, device_fp: str, title: str = "") -> str:
        """Create a new project. Returns project_id."""
        project_id = uuid.uuid4().hex[:12]
        now = _now_iso()

        project_dir = BUILD_PROJECTS_DIR / project_id
        project_dir.mkdir(parents=True, exist_ok=True)

        await self.db.execute(
            """INSERT INTO build_projects
               (project_id, device_fp, title, status, step_index, total_steps, created_at, updated_at)
               VALUES (?, ?, ?, 'planning', 0, 0, ?, ?)""",
            (project_id, device_fp, title, now, now),
        )
        await self.db.commit()
        return project_id

    async def read_project_md(self, project_id: str) -> str:
        """Read PROJECT.md content."""
        md_path = BUILD_PROJECTS_DIR / project_id / "PROJECT.md"
        if not md_path.exists():
            return ""
        return md_path.read_text(encoding="utf-8")

    async def write_project_md(self, project_id: str, content: str) -> None:
        """Write PROJECT.md content."""
        project_dir = BUILD_PROJECTS_DIR / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        md_path = project_dir / "PROJECT.md"
        md_path.write_text(content, encoding="utf-8")
        await self._touch_updated(project_id)

    async def update_status(
        self,
        project_id: str,
        *,
        status: str | None = None,
        title: str | None = None,
        step_index: int | None = None,
        total_steps: int | None = None,
    ) -> None:
        """Update project metadata fields."""
        sets: list[str] = []
        params: list[Any] = []

        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if title is not None:
            sets.append("title = ?")
            params.append(title)
        if step_index is not None:
            sets.append("step_index = ?")
            params.append(step_index)
        if total_steps is not None:
            sets.append("total_steps = ?")
            params.append(total_steps)

        if not sets:
            return

        sets.append("updated_at = ?")
        params.append(_now_iso())
        params.append(project_id)

        await self.db.execute(
            f"UPDATE build_projects SET {', '.join(sets)} WHERE project_id = ?",
            params,
        )
        await self.db.commit()

    async def get_project(self, project_id: str) -> dict[str, Any] | None:
        """Get project metadata."""
        cursor = await self.db.execute(
            "SELECT * FROM build_projects WHERE project_id = ?",
            (project_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_projects(
        self, device_fp: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """List projects for a device, most recent first."""
        cursor = await self.db.execute(
            """SELECT project_id, title, status, step_index, total_steps,
                      created_at, updated_at
               FROM build_projects
               WHERE device_fp = ?
               ORDER BY updated_at DESC LIMIT ?""",
            (device_fp, limit),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def delete_project(self, project_id: str) -> None:
        """Delete project metadata and files."""
        import shutil

        project_dir = BUILD_PROJECTS_DIR / project_id
        if project_dir.exists():
            shutil.rmtree(project_dir, ignore_errors=True)

        await self.db.execute(
            "DELETE FROM build_projects WHERE project_id = ?",
            (project_id,),
        )
        await self.db.commit()

    async def _touch_updated(self, project_id: str) -> None:
        await self.db.execute(
            "UPDATE build_projects SET updated_at = ? WHERE project_id = ?",
            (_now_iso(), project_id),
        )
        await self.db.commit()


# Singleton
project_manager = ProjectManager()
