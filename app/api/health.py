"""Health and root endpoints."""

import asyncio
import logging
import time

from fastapi import APIRouter, Request

from app.config import get_settings
from app.models.responses import HealthResponse, JiraConnectionInfo, TeamsConnectionInfo
from app.services.config_warnings import get_config_warnings as _config_warnings
from app.services.jira_client import JiraClient

logger = logging.getLogger(__name__)

router = APIRouter()

jira_client = JiraClient()

_HEALTH_CACHE_TTL = 30.0
_health_cache: dict = {"at": 0.0, "services": None}
_health_lock = asyncio.Lock()


async def _teams_status() -> dict:
    """Teams workflow webhook status — alerting basis only, not approval gating."""
    settings = get_settings()
    url = settings.TEAMS_WORKFLOW_WEBHOOK_URL or settings.TEAMS_WEBHOOK_URL
    if not url:
        return {"connected": False, "details": "Teams workflow webhook not configured — release_ready alerts skipped (set TEAMS_WORKFLOW_WEBHOOK_URL, see scripts/send_to_teams.py)"}
    # Basic URL validation (Power Automate URLs are long https://prod-*.logic.azure.com/...)
    if not url.startswith("https://"):
        return {"connected": False, "details": f"Teams webhook URL looks invalid (must start with https://): {url[:40]}..."}
    return {"connected": True, "details": f"Teams workflow webhook configured — release_ready alerts enabled (alerting basis) | URL: {url[:50]}..."}


async def _check_services() -> dict:
    """Connection status for Jira + Teams, cached to avoid hammering
    the external API on every health-scraper request."""
    now = time.monotonic()
    if _health_cache["services"] is not None and now - _health_cache["at"] < _HEALTH_CACHE_TTL:
        return _health_cache["services"]

    async with _health_lock:
        now = time.monotonic()
        if _health_cache["services"] is not None and now - _health_cache["at"] < _HEALTH_CACHE_TTL:
            return _health_cache["services"]
        jira_status = await jira_client.check_connection()
        teams_status = await _teams_status()
        warnings = _config_warnings()
        details = jira_status["details"]
        if warnings:
            details += " | Config warnings: " + "; ".join(warnings)

        services = {
            "jira": JiraConnectionInfo(connected=jira_status["connected"], details=details),
            "teams": TeamsConnectionInfo(connected=teams_status["connected"], details=teams_status["details"]),
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
    teams_info = services.get("teams")
    # Return degraded when Jira is disconnected so monitoring can alert (was always ok)
    # Teams is alerting-only, so its disconnected state does not mark degraded (info only)
    status = "ok" if (jira_info and jira_info.connected) else "degraded"
    return HealthResponse(
        status=status,
        service=settings.APP_NAME,
        environment=settings.APP_ENV,
        jira=jira_info,
        teams=teams_info,
    )
