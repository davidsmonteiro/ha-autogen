"""Tests for the database layer."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from autogen.db.database import Database


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    """Create a temporary database for testing."""
    db_path = str(tmp_path / "test.db")
    database = Database(db_path=db_path)
    await database.connect()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_connect_creates_tables(db: Database) -> None:
    async with db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ) as cursor:
        tables = {row["name"] for row in await cursor.fetchall()}
    assert "generations" in tables
    assert "deployments" in tables
    assert "reviews" in tables
    assert "prompt_templates" in tables
    assert "settings" in tables
    assert "schema_version" in tables


@pytest.mark.asyncio
async def test_schema_version_is_set(db: Database) -> None:
    async with db.conn.execute("SELECT version FROM schema_version") as cursor:
        row = await cursor.fetchone()
    assert row is not None
    assert row["version"] == 6


@pytest.mark.asyncio
async def test_insert_and_read_generation(db: Database) -> None:
    await db.conn.execute(
        """INSERT INTO generations (id, request, yaml_output, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))""",
        ("test1", "Turn on lights", "alias: test", "valid"),
    )
    await db.conn.commit()

    async with db.conn.execute(
        "SELECT * FROM generations WHERE id = ?", ("test1",)
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    assert row["request"] == "Turn on lights"
    assert row["status"] == "valid"


@pytest.mark.asyncio
async def test_insert_deployment_with_fk(db: Database) -> None:
    # Insert parent generation first
    await db.conn.execute(
        """INSERT INTO generations (id, request, yaml_output, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))""",
        ("gen1", "test request", "alias: test", "valid"),
    )
    await db.conn.execute(
        """INSERT INTO deployments (id, generation_id, yaml_deployed, status, deployed_at)
           VALUES (?, ?, ?, ?, datetime('now'))""",
        ("dep1", "gen1", "alias: test", "deployed"),
    )
    await db.conn.commit()

    async with db.conn.execute(
        "SELECT * FROM deployments WHERE id = ?", ("dep1",)
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    assert row["generation_id"] == "gen1"


@pytest.mark.asyncio
async def test_get_set_setting(db: Database) -> None:
    """Settings can be persisted and retrieved."""
    assert await db.get_setting("llm_backend") is None

    await db.set_setting("llm_backend", "openai_compat")
    assert await db.get_setting("llm_backend") == "openai_compat"

    # Upsert overwrites
    await db.set_setting("llm_backend", "ollama")
    assert await db.get_setting("llm_backend") == "ollama"


@pytest.mark.asyncio
async def test_get_all_settings(db: Database) -> None:
    """get_all_settings returns all persisted key-value pairs."""
    assert await db.get_all_settings() == {}

    await db.set_setting("llm_backend", "openai_compat")
    await db.set_setting("llm_model", "gpt-4")
    result = await db.get_all_settings()
    assert result == {"llm_backend": "openai_compat", "llm_model": "gpt-4"}


@pytest.mark.asyncio
async def test_settings_persist_across_reopen(tmp_path: Path) -> None:
    """Settings survive a close/reopen cycle."""
    db_path = str(tmp_path / "settings_persist.db")
    db = Database(db_path=db_path)
    await db.connect()
    await db.set_setting("llm_api_url", "https://openrouter.ai/api")
    await db.close()

    db2 = Database(db_path=db_path)
    await db2.connect()
    assert await db2.get_setting("llm_api_url") == "https://openrouter.ai/api"
    await db2.close()


@pytest.mark.asyncio
async def test_close_and_reopen(tmp_path: Path) -> None:
    db_path = str(tmp_path / "reopen.db")
    db = Database(db_path=db_path)
    await db.connect()

    await db.conn.execute(
        """INSERT INTO generations (id, request, yaml_output, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))""",
        ("persist1", "test", "yaml", "valid"),
    )
    await db.conn.commit()
    await db.close()

    # Reopen — data should persist and migration should not re-run
    db2 = Database(db_path=db_path)
    await db2.connect()
    async with db2.conn.execute(
        "SELECT * FROM generations WHERE id = ?", ("persist1",)
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    await db2.close()
