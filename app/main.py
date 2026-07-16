"""RAB Automation Service – FastAPI application entry point."""

import logging

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from app.api.metrics import MetricsMiddleware, router as metrics_router
from app.api.routes import api_router
from app.config import get_settings
from app.database import close_db, init_db
from app.logging_config import setup_logging
from app.services.task_queue import get_task_queue

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_application: FastAPI):
    await init_db()
    get_task_queue().start()
    yield
    await get_task_queue().stop()
    await close_db()


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL)

    application = FastAPI(
        title="RAB Automation Service",
        version="0.4.0",
        description="Lightweight Jira RAB automation webhook service",
        lifespan=lifespan,
    )

    application.state.settings = settings

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.is_dir():
        application.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    application.include_router(api_router)
    application.include_router(metrics_router)
    application.add_middleware(MetricsMiddleware)

    @application.get("/")
    async def root_redirect():
        return RedirectResponse(url="/dashboard/health")

    logger.info(
        "RAB Automation Service started: app=%s, env=%s",
        settings.APP_NAME,
        settings.APP_ENV,
    )

    return application


app = create_app()
