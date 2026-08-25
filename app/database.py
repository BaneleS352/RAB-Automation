"""Async SQLite database setup and connection management."""

import asyncio
import logging
from pathlib import Path

import aiosqlite

from app.config import get_settings

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "rab_automation.db"


def _get_db_path() -> Path:
    settings = get_settings()
    if settings.DATABASE_PATH:
        return Path(settings.DATABASE_PATH)
    return _DEFAULT_DB_PATH


DB_PATH = _get_db_path()

_connection: aiosqlite.Connection | None = None
_db_lock = asyncio.Lock()
_db_path_cached: Path | None = None


async def get_db() -> aiosqlite.Connection:
    global _connection, _db_path_cached
    # Re-resolve path if env changed (fixes frozen DB_PATH at import)
    current_path = _get_db_path()
    if _connection is not None and _db_path_cached is not None and current_path != _db_path_cached:
        # Path changed — close old connection
        try:
            await _connection.close()
        except Exception:
            pass
        _connection = None
    if _connection is None:
        async with _db_lock:
            if _connection is None:
                current_path = _get_db_path()
                _connection = await aiosqlite.connect(str(current_path))
                _connection.row_factory = aiosqlite.Row
                try:
                    await _connection.execute("PRAGMA journal_mode=WAL")
                    await _connection.execute("PRAGMA busy_timeout=5000")
                    await _connection.commit()
                except Exception:
                    pass
                _db_path_cached = current_path
                logger.info("Database connection opened: %s", current_path)
    return _connection


async def close_db() -> None:
    global _connection
    async with _db_lock:
        if _connection:
            try:
                await _connection.close()
            except Exception:
                pass
            _connection = None
            logger.info("Database connection closed.")


async def _migrate(db: aiosqlite.Connection) -> None:
    """Idempotent additive schema migrations for existing databases."""
    rows = await db.execute_fetchall("PRAGMA table_info(rab_records)")
    columns = {r["name"] for r in rows}
    if "sdl_approval_id" not in columns:
        await db.execute("ALTER TABLE rab_records ADD COLUMN sdl_approval_id TEXT DEFAULT ''")
    if "sdm_approval_id" not in columns:
        await db.execute("ALTER TABLE rab_records ADD COLUMN sdm_approval_id TEXT DEFAULT ''")
    if "creator" not in columns:
        await db.execute("ALTER TABLE rab_records ADD COLUMN creator TEXT DEFAULT ''")
    if "assignee" not in columns:
        await db.execute("ALTER TABLE rab_records ADD COLUMN assignee TEXT DEFAULT ''")
    await db.execute("""CREATE TABLE IF NOT EXISTS field_change_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, issue_key TEXT NOT NULL, field TEXT NOT NULL,
        from_value TEXT DEFAULT '', to_value TEXT DEFAULT '', author TEXT DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""")


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
            sdl_approval_id TEXT DEFAULT '',
            sdm_approval_id TEXT DEFAULT '',
            rejection_reason TEXT DEFAULT '',
            rejected_by     TEXT DEFAULT '',
            meeting_needed  INTEGER DEFAULT 0,
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

        CREATE TABLE IF NOT EXISTS field_change_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_key TEXT NOT NULL,
            field TEXT NOT NULL,
            from_value TEXT DEFAULT '',
            to_value TEXT DEFAULT '',
            author TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_rab_issue ON rab_records(issue_key);
        CREATE INDEX IF NOT EXISTS idx_approval_issue ON approval_events(issue_key);
        CREATE INDEX IF NOT EXISTS idx_webhook_event_id ON webhook_events(event_id);
        CREATE INDEX IF NOT EXISTS idx_field_change_issue ON field_change_events(issue_key);
    """)
    await db.commit()
    await _migrate(db)
    await db.commit()
    logger.info("Database schema initialized.")
