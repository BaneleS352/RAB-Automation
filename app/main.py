"""RAB Automation Service – FastAPI application entry point."""

import logging

from fastapi import FastAPI

from app.api.routes import api_router
from app.config import get_settings
from app.logging_config import setup_logging

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()

    setup_logging(settings.LOG_LEVEL)

    application = FastAPI(
        title="RAB Automation Service",
        version="0.1.0",
        description="Lightweight Jira RAB automation webhook service",
    )

    # Store settings on app state so routes can access them via request.app.state
    application.state.settings = settings

    # Register routers
    application.include_router(api_router)

    logger.info(
        "RAB Automation Service started: app=%s, env=%s",
        settings.APP_NAME,
        settings.APP_ENV,
    )

    return application


app = create_app()
