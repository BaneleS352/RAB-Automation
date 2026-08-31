"""Health and root endpoints."""

import asyncio
import logging
import time

from fastapi import APIRouter, Request

from app.models.responses import HealthResponse, JiraConnectionInfo
from app.services.config_warnings import get_config_warnings as _config_warnings
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
        warnings = _config_warnings()
        details = jira_status["details"]
        if warnings:
            details += " | Config warnings: " + "; ".join(warnings)

        services = {
            "jira": JiraConnectionInfo(connected=jira_status["connected"], details=details),
        }
        # Expose warnings separately for dashboard banner (not part of health JSON contract, but available via health_details)
        services["_warnings"] = warnings  # internal, not serialized via HealthResponse
        _health_cache["at"] = now
        _health_cache["services"] = services
        return services


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    services = await _check_services()
    jira_info = services.get("jira")
    # Return degraded when Jira is disconnected so monitoring can alert (was always ok)
    status = "ok" if (jira_info and jira_info.connected) else "degraded"
    return HealthResponse(
        status=status,
        service=settings.APP_NAME,
        environment=settings.APP_ENV,
        jira=jira_info,
    )
