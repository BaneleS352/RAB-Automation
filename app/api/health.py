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

# NOTE: JiraClient is constructed per health check (not at import) so credential
# changes take effect without a restart. A module-level singleton would freeze
# base_url/email/token from the first get_settings() call.

_HEALTH_CACHE_TTL = 30.0
_health_cache: dict = {"at": 0.0, "services": None}
_health_lock = asyncio.Lock()


def _teams_status(settings=None) -> dict:
    """Teams workflow webhook status — alerting basis only, not approval gating.

    NOTE: `connected` here means "configured" — the workflow URL is never probed
    (a probe POST would fire a real Teams alert). A configured URL can still fail
    at send time (deleted flow, rotated sig); send failures are logged per alert.
    """
    settings = settings if settings is not None else get_settings()
    url = settings.effective_teams_webhook_url
    if not url:
        return {"connected": False, "details": "Teams workflow webhook not configured — release_ready alerts skipped (set TEAMS_WORKFLOW_WEBHOOK_URL, see scripts/send_to_teams.py)"}
    # Basic URL validation (Power Automate URLs are long https://prod-*.logic.azure.com/...)
    if not url.startswith("https://"):
        return {"connected": False, "details": f"Teams webhook URL looks invalid (must start with https://): {url[:40]}..."}
    return {"connected": True, "details": "Teams workflow webhook configured (not probed — a probe would fire a real alert) — release_ready alerts enabled (alerting basis)"}


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
        # Resolve settings once and share it: get_settings() re-parses .env on
        # every call (deliberately uncached for test freshness).
        settings = get_settings()
        jira_status = await JiraClient(settings).check_connection()
        teams_status = _teams_status(settings)
        warnings = _config_warnings(settings)
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
