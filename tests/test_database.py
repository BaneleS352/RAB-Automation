"""Tests for the SQLite database layer."""

import pytest

from app.database import get_db, init_db, close_db


class TestDatabase:
    @pytest.mark.asyncio
    async def test_init_db_creates_tables(self) -> None:
        await init_db()
        db = await get_db()
        tables = await db.execute_fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        names = [row[0] for row in tables]
        assert "rab_records" in names
        assert "approval_events" in names
        assert "webhook_events" in names

    @pytest.mark.asyncio
    async def test_init_db_is_idempotent(self) -> None:
        await init_db()
        await init_db()
        db = await get_db()
        tables = await db.execute_fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        assert len(tables) >= 3

    @pytest.mark.asyncio
    async def test_get_db_returns_connection(self) -> None:
        db = await get_db()
        assert db is not None
        result = await db.execute_fetchall("SELECT 1 as val")
        assert result[0][0] == 1

    @pytest.mark.asyncio
    async def test_close_db_does_not_raise(self) -> None:
        await close_db()
        await close_db()

    @pytest.mark.asyncio
    async def test_rab_records_schema(self) -> None:
        await init_db()
        db = await get_db()
        cols = await db.execute_fetchall("PRAGMA table_info(rab_records)")
        col_names = {row[1] for row in cols}
        expected = {
            "id", "issue_key", "summary", "status",
            "validation_result", "sdl_approval", "sdm_approval",
            "rejection_reason", "rejected_by", "meeting_needed",
            "azure_pr_status", "azure_pipeline_status",
            "created_at", "updated_at",
        }
        assert col_names == expected

    @pytest.mark.asyncio
    async def test_approval_events_schema(self) -> None:
        await init_db()
        db = await get_db()
        cols = await db.execute_fetchall("PRAGMA table_info(approval_events)")
        col_names = {row[1] for row in cols}
        assert "issue_key" in col_names
        assert "step" in col_names
        assert "action" in col_names
        assert "approver" in col_names

    @pytest.mark.asyncio
    async def test_webhook_events_unique_event_id(self) -> None:
        await init_db()
        db = await get_db()
        unique_id = "dup-test-" + str(id(self))
        await db.execute(
            "INSERT INTO webhook_events (event_id, issue_key, event_type) VALUES (?, ?, ?)",
            (unique_id, "TEST-1", "test"),
        )
        await db.commit()
        with pytest.raises(Exception):
            await db.execute(
                "INSERT INTO webhook_events (event_id, issue_key, event_type) VALUES (?, ?, ?)",
                (unique_id, "TEST-1", "test"),
            )
            await db.commit()
