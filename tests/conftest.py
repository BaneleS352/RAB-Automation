"""pytest fixtures and configuration."""

import asyncio
import logging
import os
import tempfile
import uuid

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_PATH"] = os.path.join(
    tempfile.gettempdir(), f"rab_pytest_{uuid.uuid4().hex}.db"
)



from app.database import DB_PATH, close_db, init_db

logger = logging.getLogger(__name__)


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
