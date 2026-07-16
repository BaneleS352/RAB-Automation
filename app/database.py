"""Async SQLite database setup and connection management."""

import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "rab_automation.db"

_connection: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _connection
    if _connection is None:
        _connection = await aiosqlite.connect(str(DB_PATH))
        _connection.row_factory = aiosqlite.Row
        logger.info("Database connection opened: %s", DB_PATH)
    return _connection


async def close_db() -> None:
    global _connection
    if _connection:
        await _connection.close()
        _connection = None
        logger.info("Database connection closed.")


async def init_db() -> None:
    db = await get_db()
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS rab_records (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_key       TEXT NOT NULL,
            summary         TEXT DEFAULT '',
            status          TEXT NOT NULL DEFAULT 'pending',
            validation_result TEXT DEFAULT '',
            sdl_approval    TEXT DEFAULT 'pending',
            sdm_approval    TEXT DEFAULT 'pending',
            rejection_reason TEXT DEFAULT '',
            rejected_by     TEXT DEFAULT '',
            meeting_needed  INTEGER DEFAULT 0,
            azure_pr_status TEXT DEFAULT '',
            azure_pipeline_status TEXT DEFAULT '',
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS approval_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_key       TEXT NOT NULL,
            step            TEXT NOT NULL,
            action          TEXT NOT NULL,
            approver        TEXT DEFAULT '',
            reason          TEXT DEFAULT '',
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS webhook_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id        TEXT UNIQUE NOT NULL,
            issue_key       TEXT NOT NULL,
            event_type      TEXT DEFAULT '',
            status          TEXT NOT NULL DEFAULT 'received',
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_rab_issue ON rab_records(issue_key);
        CREATE INDEX IF NOT EXISTS idx_approval_issue ON approval_events(issue_key);
        CREATE INDEX IF NOT EXISTS idx_webhook_event_id ON webhook_events(event_id);
    """)
    await db.commit()
    logger.info("Database schema initialized.")
