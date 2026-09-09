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
    """Teams workflow webhook status, split by direction.

    Outbound (RAB → Teams alerts) is a Power Automate workflow webhook: POST-only
    by design, so `connected` here means "configured" — the URL is never probed
    (a probe POST would fire a real Teams alert). A configured URL can still fail
    at send time (deleted flow, rotated sig); send failures are logged per alert.

    Inbound (Teams → RAB approvals) is NOT available: no Teams callback receiver
    is mounted (nothing listens on POST /webhooks/teams or equivalent), and a
    workflow webhook cannot call back into this service on its own. Approval-
    through-Teams needs (1) a decision endpoint the flow/bot can POST to and
    (2) APP_PUBLIC_URL set so Teams/Flow can reach it. `direction` reports
    "unconfigured" | "outbound-only" | "two-way" so the Overview card can show
    at a glance which way the connection flows.
    """
    settings = settings if settings is not None else get_settings()
    url = settings.effective_teams_webhook_url
    # Inbound assessment is shared by all three outbound states below.
    # NOTE: no Teams callback receiver exists in this codebase yet — if one is
    # ever mounted (e.g. POST /webhooks/teams), set inbound_supported=True here
    # (and gate on its auth token) so `direction` flips to "two-way".
    public_url = (settings.APP_PUBLIC_URL or "").strip()
    if public_url:
        inbound_details = (
            "Inbound approvals NOT available — no Teams callback endpoint is mounted "
            "(nothing listens on POST /webhooks/teams or equivalent), so Teams cannot "
            "send decisions back into the system. APP_PUBLIC_URL is set, so reachability "
            "is ready — mounting an authenticated decision endpoint completes the loop."
        )
    else:
        inbound_details = (
            "Inbound approvals NOT available — no Teams callback endpoint is mounted "
            "(nothing listens on POST /webhooks/teams or equivalent), so Teams cannot "
            "send decisions back into the system. To enable approval-through-Teams: mount "
            "an authenticated decision endpoint AND set APP_PUBLIC_URL to this service's "
            "public base URL (Power Automate 'post card and wait for response' flows need it)."
        )
    inbound = {"supported": False, "details": inbound_details}
    if not url:
        return {
            "connected": False,
            "configured": False,
            "details": "Teams workflow webhook not configured — release_ready alerts skipped (set TEAMS_WORKFLOW_WEBHOOK_URL, see scripts/send_to_teams.py)",
            "direction": "unconfigured",
            "outbound_details": "Outbound alerts NOT configured — release_ready cards are skipped.",
            "inbound_supported": inbound["supported"],
            "inbound_details": inbound["details"],
        }
    # Basic URL validation (Power Automate URLs are long https://prod-*.logic.azure.com/...)
    # NOTE: never echo the URL itself — it is a signed secret (see _SECRET_FIELDS).
    if not url.startswith("https://"):
        return {
            "connected": False,
            "configured": True,
            "details": "Teams webhook URL is invalid (must start with https://) — alerts will fail at send time.",
            "direction": "outbound-only",
            "outbound_details": "Outbound URL present but invalid (must start with https://) — alerts will fail at send time.",
            "inbound_supported": inbound["supported"],
            "inbound_details": inbound["details"],
        }
    return {
        "connected": True,
        "configured": True,
        "details": "Teams workflow webhook configured (not probed — a probe would fire a real alert) — release_ready alerts enabled (alerting basis)",
        "direction": "outbound-only",
        "outbound_details": "Outbound alerts configured — release_ready AdaptiveCards POST to Teams (workflow URL not probed).",
        "inbound_supported": inbound["supported"],
        "inbound_details": inbound["details"],
    }


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
            # Pass the full _teams_status dict through (connected/configured/
            # details/direction/outbound_details/inbound_*) — cherry-picking
            # here silently dropped the directionality keys once before.
            "teams": teams_status,
            "_warnings": warnings,
        }
        _health_cache["at"] = now
        _health_cache["services"] = services
        return services
