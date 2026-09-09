"""Shared service-health check — single source for /health and dashboard.

Previously app/api/health.py and app/api/dashboard.py each kept their own TTL
cache and each called Jira on a miss, doubling live Jira auth calls per window.
All service-status reads go through get_service_statuses() here so exactly one
live check happens per TTL window no matter which route triggers it.
"""

import asyncio
import logging
import time

from app.config import get_settings
from app.services.config_warnings import get_config_warnings
from app.services.jira_client import JiraClient

logger = logging.getLogger(__name__)

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
        return {"connected": False, "configured": False, "details": "Teams workflow webhook not configured — release_ready alerts skipped (set TEAMS_WORKFLOW_WEBHOOK_URL, see scripts/send_to_teams.py)"}
    # Basic URL validation (Power Automate URLs are long https://prod-*.logic.azure.com/...)
    if not url.startswith("https://"):
        return {"connected": False, "configured": True, "details": f"Teams webhook URL looks invalid (must start with https://): {url[:40]}..."}
    return {"connected": True, "configured": True, "details": "Teams workflow webhook configured (not probed — a probe would fire a real alert) — release_ready alerts enabled (alerting basis)"}


async def get_service_statuses() -> dict:
    """Return cached {jira, teams, _warnings} service status (plain dicts).

    The cache is shared by every caller, so concurrent /health + dashboard hits
    within one TTL window produce a single live Jira check, not one each.
    """
    now = time.monotonic()
    if _health_cache["services"] is not None and now - _health_cache["at"] < _HEALTH_CACHE_TTL:
        return _health_cache["services"]

    async with _health_lock:
        # Double-check after acquiring lock
        now = time.monotonic()
        if _health_cache["services"] is not None and now - _health_cache["at"] < _HEALTH_CACHE_TTL:
            return _health_cache["services"]
        # Resolve settings once and share it: get_settings() re-parses .env on
        # every call (deliberately uncached for test freshness).
        settings = get_settings()
        jira_status = await JiraClient(settings).check_connection()
        teams_status = _teams_status(settings)
        warnings = get_config_warnings(settings)
        details = jira_status.get("details", "Unknown")
        if warnings:
            details += " | Config warnings: " + "; ".join(warnings)

        services = {
            "jira": {"connected": jira_status.get("connected", False), "details": details},
            "teams": {
                "connected": teams_status["connected"],
                "configured": teams_status.get("configured", True),
                "details": teams_status["details"],
            },
            "_warnings": warnings,
        }
        _health_cache["at"] = now
        _health_cache["services"] = services
        return services
