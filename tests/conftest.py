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
from app.database import DB_PATH, init_db, close_db
from app.api.webhooks import orchestrator
from app.services.approval_service import ApprovalService


logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    try:
        get_settings.cache_clear()  # type: ignore[attr-defined]
    except AttributeError:
        pass
    yield
    try:
        get_settings.cache_clear()  # type: ignore[attr-defined]
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
    if DB_PATH.exists():
        try:
            DB_PATH.unlink()
        except PermissionError:
            logger.warning("Could not delete existing test DB %s (locked) — reusing it", DB_PATH)
    asyncio.run(init_db())


def _close():
    asyncio.run(close_db())


def pytest_sessionfinish(session, exitstatus):
    """Close the SQLite connection so the process can exit cleanly."""
    _close()


_init()
