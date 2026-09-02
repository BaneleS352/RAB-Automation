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
        async with _db_lock:
            if _connection is not None and _db_path_cached != current_path:
                try:
                    await _connection.close()
                except Exception:
                    pass
                _connection = None
                _db_path_cached = None
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
                except Exception as e:
                    logger.warning("PRAGMA setup failed for %s: %s", current_path, e)
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
    # Rich Jira fields — added to fix blank-details (issue persist only summary/creator/assignee)
    if "description" not in columns:
        await db.execute("ALTER TABLE rab_records ADD COLUMN description TEXT DEFAULT ''")
    if "priority" not in columns:
        await db.execute("ALTER TABLE rab_records ADD COLUMN priority TEXT DEFAULT ''")
    if "issuetype" not in columns:
        await db.execute("ALTER TABLE rab_records ADD COLUMN issuetype TEXT DEFAULT ''")
    if "jira_status" not in columns:
        await db.execute("ALTER TABLE rab_records ADD COLUMN jira_status TEXT DEFAULT ''")
    if "labels" not in columns:
        await db.execute("ALTER TABLE rab_records ADD COLUMN labels TEXT DEFAULT ''")
    if "reporter" not in columns:
        await db.execute("ALTER TABLE rab_records ADD COLUMN reporter TEXT DEFAULT ''")
    if "jira_updated" not in columns:
        await db.execute("ALTER TABLE rab_records ADD COLUMN jira_updated TEXT DEFAULT ''")
    if "raw_fields" not in columns:
        await db.execute("ALTER TABLE rab_records ADD COLUMN raw_fields TEXT DEFAULT ''")
    for column in ("deployment_instructions", "outcome_notes", "rollback_strategy", "mitigation_strategy",
                   "related_release_reference", "release_outcome", "environments", "development",
                   "parent_reference", "sprint"):
        if column not in columns:
            await db.execute(f"ALTER TABLE rab_records ADD COLUMN {column} TEXT DEFAULT ''")
    if "jira_exists" not in columns:
        await db.execute("ALTER TABLE rab_records ADD COLUMN jira_exists INTEGER NOT NULL DEFAULT 1")
    if "jira_last_seen" not in columns:
        await db.execute("ALTER TABLE rab_records ADD COLUMN jira_last_seen TEXT DEFAULT ''")
    # Systemic fix: issue_key should be unique; previously only a non-unique index existed,
    # allowing silent duplicate rows on concurrent webhooks (similar to blank-details silent duplication).
    # Deduplicate keeping latest row, then enforce uniqueness and drop redundant non-unique index.
    try:
        dups = await db.execute_fetchall("SELECT issue_key, COUNT(*) c FROM rab_records GROUP BY issue_key HAVING c > 1")
        for row in dups:
            key = row["issue_key"]
            keep = await db.execute_fetchall("SELECT id FROM rab_records WHERE issue_key = ? ORDER BY id DESC LIMIT 1", (key,))
            keep_id = keep[0]["id"] if keep else None
            if keep_id:
                await db.execute("DELETE FROM rab_records WHERE issue_key = ? AND id != ?", (key, keep_id))
                logger.warning("Deduplicated rab_records for %s, kept id %s", key, keep_id)
        await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS uidx_rab_issue_key ON rab_records(issue_key)")
        # Non-unique idx_rab_issue is now redundant and wastes write overhead
        await db.execute("DROP INDEX IF EXISTS idx_rab_issue")
    except Exception as e:
        logger.warning("Could not create unique index on rab_records.issue_key: %s", e)
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
            description     TEXT DEFAULT '',
            priority        TEXT DEFAULT '',
            issuetype       TEXT DEFAULT '',
            jira_status     TEXT DEFAULT '',
            labels          TEXT DEFAULT '',
            reporter        TEXT DEFAULT '',
            jira_updated    TEXT DEFAULT '',
            raw_fields      TEXT DEFAULT '',
            deployment_instructions TEXT DEFAULT '',
            outcome_notes   TEXT DEFAULT '',
            rollback_strategy TEXT DEFAULT '',
            mitigation_strategy TEXT DEFAULT '',
            related_release_reference TEXT DEFAULT '',
            release_outcome TEXT DEFAULT '',
            environments    TEXT DEFAULT '',
            development     TEXT DEFAULT '',
            parent_reference TEXT DEFAULT '',
            sprint          TEXT DEFAULT '',
            jira_exists     INTEGER NOT NULL DEFAULT 1,
            jira_last_seen  TEXT DEFAULT '',
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

        CREATE UNIQUE INDEX IF NOT EXISTS uidx_rab_issue_key ON rab_records(issue_key);
        CREATE INDEX IF NOT EXISTS idx_approval_issue ON approval_events(issue_key);
        CREATE INDEX IF NOT EXISTS idx_webhook_event_id ON webhook_events(event_id);
        CREATE INDEX IF NOT EXISTS idx_field_change_issue ON field_change_events(issue_key);
    """)
    await db.commit()
    await _migrate(db)
    await db.commit()
    logger.info("Database schema initialized.")
