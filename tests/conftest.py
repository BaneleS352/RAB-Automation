"""pytest fixtures and configuration."""

import asyncio
import os

os.environ["APP_ENV"] = "test"

from pathlib import Path

from app.database import _connection, DB_PATH, close_db, init_db


def _init():
    if DB_PATH.exists():
        DB_PATH.unlink()
    asyncio.run(init_db())


def _close():
    asyncio.run(close_db())


_init()
