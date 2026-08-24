"""pytest fixtures and configuration."""

import asyncio
import logging
import os
import tempfile
import uuid

import pytest

from app.database import DB_PATH, init_db, close_db
from app.api.webhooks import orchestrator

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_PATH"] = os.path.join(
    tempfile.gettempdir(), f"rab_pytest_{uuid.uuid4().hex}.db"
)


from app.services.approval_service import ApprovalService, _store

logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def _reset_approval_service() -> None:
    """Reset approval service state between tests to prevent carryover."""
    service = ApprovalService()
    service.reset()
    _store.clear()
    orchestrator.approval_service.reset()
    orchestrator.approval_service._store.clear()
    _store.clear()
    yield
    service.reset()
    _store.clear()
    orchestrator.approval_service.reset()
    orchestrator.approval_service._store.clear()
    _store.clear()


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