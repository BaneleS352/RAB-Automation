"""Health and root endpoints."""

import asyncio
import logging
import time

from fastapi import APIRouter, Request

from app.models.responses import HealthResponse, JiraConnectionInfo
from app.services.jira_client import JiraClient

logger = logging.getLogger(__name__)

router = APIRouter()

jira_client = JiraClient()

_HEALTH_CACHE_TTL = 30.0
_health_cache: dict = {"at": 0.0, "services": None}
_health_lock = asyncio.Lock()


async def _check_services() -> dict:
    """Connection status for Jira, cached to avoid hammering
    the external API on every health-scraper request."""
    now = time.monotonic()
    if _health_cache["services"] is not None and now - _health_cache["at"] < _HEALTH_CACHE_TTL:
        return _health_cache["services"]

    async with _health_lock:
        now = time.monotonic()
        if _health_cache["services"] is not None and now - _health_cache["at"] < _HEALTH_CACHE_TTL:
            return _health_cache["services"]
        jira_status = await jira_client.check_connection()

        services = {
            "jira": JiraConnectionInfo(connected=jira_status["connected"], details=jira_status["details"]),
        }
        _health_cache["at"] = now
        _health_cache["services"] = services
        return services


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    services = await _check_services()
    # Only include jira; azure_devops and teams have been removed
    jira_info = services.get("jira")
    return HealthResponse(
        status="ok",
        service=settings.APP_NAME,
        environment=settings.APP_ENV,
        jira=jira_info,
    )
