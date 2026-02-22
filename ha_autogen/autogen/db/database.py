"""SQLite database setup and migrations via aiosqlite."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)


def _get_db_path() -> str:
    """Return the database file path (production vs dev mode)."""
    if os.environ.get("AUTOGEN_DEV_MODE", "").lower() == "true":
        db_dir = Path(__file__).resolve().parent.parent.parent.parent / "data"
        db_dir.mkdir(exist_ok=True)
        return str(db_dir / "ha_autogen.db")
    db_dir = Path("/data")
    db_dir.mkdir(exist_ok=True)
    return str(db_dir / "ha_autogen.db")


SCHEMA_VERSION = 4

MIGRATIONS: dict[int, list[str]] = {
    1: [
        """
        CREATE TABLE IF NOT EXISTS generations (
            id              TEXT PRIMARY KEY,
            request         TEXT NOT NULL,
            yaml_output     TEXT NOT NULL,
            raw_response    TEXT DEFAULT '',
            model           TEXT DEFAULT '',
            prompt_tokens   INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            validation_json TEXT DEFAULT '{}',
            retries         INTEGER DEFAULT 0,
            status          TEXT DEFAULT 'draft',
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS deployments (
            id              TEXT PRIMARY KEY,
            generation_id   TEXT NOT NULL,
            automation_id   TEXT,
            yaml_deployed   TEXT NOT NULL,
            backup_path     TEXT,
            status          TEXT DEFAULT 'deployed',
            deployed_at     TEXT NOT NULL DEFAULT (datetime('now')),
            rolled_back_at  TEXT,
            FOREIGN KEY (generation_id) REFERENCES generations(id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS reviews (
            id              TEXT PRIMARY KEY,
            scope           TEXT NOT NULL DEFAULT 'all',
            target_id       TEXT,
            findings_json   TEXT NOT NULL DEFAULT '[]',
            summary         TEXT DEFAULT '',
            model           TEXT DEFAULT '',
            prompt_tokens   INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL
        )
        """,
        "INSERT INTO schema_version (version) VALUES (1)",
    ],
    2: [
        "ALTER TABLE generations ADD COLUMN type TEXT DEFAULT 'automation'",
        "ALTER TABLE deployments ADD COLUMN type TEXT DEFAULT 'automation'",
        "UPDATE schema_version SET version = 2",
    ],
    3: [
        """
        CREATE TABLE IF NOT EXISTS prompt_templates (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            content     TEXT NOT NULL,
            target      TEXT NOT NULL DEFAULT 'system',
            position    TEXT NOT NULL DEFAULT 'append',
            enabled     INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """,
        "UPDATE schema_version SET version = 3",
    ],
    4: [
        """
        CREATE TABLE IF NOT EXISTS plans (
            id                TEXT PRIMARY KEY,
            request           TEXT NOT NULL,
            mode              TEXT NOT NULL DEFAULT 'automation',
            plan_json         TEXT NOT NULL DEFAULT '{}',
            context_block     TEXT DEFAULT '',
            model             TEXT DEFAULT '',
            prompt_tokens     INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            status            TEXT DEFAULT 'pending',
            generation_id     TEXT,
            iteration         INTEGER DEFAULT 1,
            created_at        TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (generation_id) REFERENCES generations(id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS fix_applications (
            id              TEXT PRIMARY KEY,
            review_id       TEXT NOT NULL,
            finding_id      TEXT NOT NULL,
            fix_type        TEXT NOT NULL DEFAULT 'quick',
            fix_yaml        TEXT NOT NULL,
            automation_id   TEXT,
            status          TEXT DEFAULT 'applied',
            applied_at      TEXT NOT NULL DEFAULT (datetime('now')),
            rolled_back_at  TEXT,
            FOREIGN KEY (review_id) REFERENCES reviews(id)
        )
        """,
        "UPDATE schema_version SET version = 4",
    ],
}


class Database:
    """Async SQLite wrapper with migration support."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _get_db_path()
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open the database connection and run pending migrations."""
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._run_migrations()

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        """Return the active connection (asserts it exists)."""
        assert self._conn is not None, "Database not connected"
        return self._conn

    async def _run_migrations(self) -> None:
        """Apply any pending schema migrations."""
        try:
            async with self.conn.execute(
                "SELECT version FROM schema_version LIMIT 1"
            ) as cursor:
                row = await cursor.fetchone()
                current = row["version"] if row else 0
        except Exception:
            current = 0

        for version in sorted(MIGRATIONS.keys()):
            if version > current:
                for sql in MIGRATIONS[version]:
                    await self.conn.execute(sql)
                await self.conn.commit()
                logger.info("Applied database migration v%d", version)
