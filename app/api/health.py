"""Health and root endpoints."""

from fastapi import APIRouter, Request

from app.models.responses import HealthResponse, JiraConnectionInfo, TeamsConnectionInfo
from app.services import health_check as _health_check_mod
from app.services.health_check import get_service_statuses

router = APIRouter()

# NOTE: JiraClient is constructed per health check (not at import) so credential
# changes take effect without a restart. A module-level singleton would freeze
# base_url/email/token from the first get_settings() call.

# Shared cache lives in app.services.health_check so /health and the dashboard
# trigger at most one live Jira check per TTL window. Aliased (same object) so
# existing `from app.api.health import _health_cache` references keep working.
_HEALTH_CACHE_TTL = _health_check_mod._HEALTH_CACHE_TTL
_health_cache = _health_check_mod._health_cache
_health_lock = _health_check_mod._health_lock


async def _check_services() -> dict:
    """Connection status for Jira + Teams, cached to avoid hammering
    the external API on every health-scraper request."""
    raw = await get_service_statuses()
    services = {
        "jira": JiraConnectionInfo(**{k: raw["jira"][k] for k in ("connected", "details")}),
        "teams": TeamsConnectionInfo(
            **{k: raw["teams"][k] for k in ("connected", "details")},
            configured=raw["teams"].get("configured", True),
        ),
    }
    # Expose warnings separately for dashboard banner (not part of health JSON contract, but available via health_details)
    services["_warnings"] = raw.get("_warnings", [])  # internal, not serialized via HealthResponse
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
