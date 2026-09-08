"""pytest fixtures and configuration."""

import asyncio
import logging
import os
import tempfile
import uuid

import pytest

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_PATH"] = os.path.join(
    tempfile.gettempdir(), f"rab_pytest_{uuid.uuid4().hex}.db"
)

from app.config import get_settings
from app.database import _get_db_path, init_db, close_db
from app.api.webhooks import orchestrator


logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    try:
        get_settings.cache_clear()  # type: ignore[attr-defined]
    except AttributeError:
        pass
    try:
        from app.config import _resolve_vault_secrets
        _resolve_vault_secrets.cache_clear()  # type: ignore[attr-defined]
    except AttributeError:
        pass
    yield
    try:
        get_settings.cache_clear()  # type: ignore[attr-defined]
    except AttributeError:
        pass
    try:
        from app.config import _resolve_vault_secrets
        _resolve_vault_secrets.cache_clear()  # type: ignore[attr-defined]
    except AttributeError:
        pass


@pytest.fixture(autouse=True)
def _reset_approval_service() -> None:
    """Reset approval service + DB state between tests to prevent carryover."""
    # Clear DB records (rab_records is the source of the ABC-123 carryover)
    asyncio.run(_clear_test_records())
    orchestrator.approval_service.reset()
    yield
    asyncio.run(_clear_test_records())
    orchestrator.approval_service.reset()


async def _clear_test_records() -> None:
    from app.database import get_db
    db = await get_db()
    await db.execute("DELETE FROM rab_records")
    await db.execute("DELETE FROM approval_events")
    await db.execute("DELETE FROM webhook_events")
    await db.execute("DELETE FROM field_change_events")
    await db.commit()


def _init():
    # Resolve fresh (not the frozen DB_PATH constant) so a moved DATABASE_PATH is honored
    db_path = _get_db_path()
    if db_path.exists():
        try:
            db_path.unlink()
        except PermissionError:
            logger.warning("Could not delete existing test DB %s (locked) — reusing it", db_path)
    asyncio.run(init_db())


def _close():
    asyncio.run(close_db())


def pytest_sessionfinish(session, exitstatus):
    """Close the SQLite connection so the process can exit cleanly."""
    _close()


_init()
