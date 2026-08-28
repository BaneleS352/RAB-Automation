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


def _config_warnings() -> list[str]:
    """Surface silent no-ops that previously caused 'blank details' without any health signal."""
    from app.config import get_settings
    s = get_settings()
    warns: list[str] = []
    if not s.JIRA_PROJECT_KEY:
        warns.append("JIRA_PROJECT_KEY empty — sync falls back to unfiltered 'ORDER BY updated DESC' (cross-project, first 100)")
    # Field mappings — 10 RAB custom fields; if all empty, validator now falls back to description parsing (was previously blank)
    field_vars = [
        "JIRA_FIELD_DATE_TIME", "JIRA_FIELD_RAB_APPROVER", "JIRA_FIELD_PR_LINK", "JIRA_FIELD_PIPELINE_LINK",
        "JIRA_FIELD_DEVELOPER", "JIRA_FIELD_TEAM_LEAD", "JIRA_FIELD_PM", "JIRA_FIELD_QA",
        "JIRA_FIELD_ENVIRONMENT", "JIRA_FIELD_ROLLBACK_DETAILS",
    ]
    missing = sum(1 for v in field_vars if not getattr(s, v, ""))
    if missing >= 8:
        warns.append(f"{missing}/10 JIRA_FIELD_* mappings empty — validator now uses description fallback (was previously blank); set customfield IDs to use native fields")
    elif missing:
        warns.append(f"{missing}/10 JIRA_FIELD_* mappings empty — description fallback active for those fields")
    if not any([s.JIRA_TRANSITION_VALIDATE, s.JIRA_TRANSITION_REQUEST_APPROVAL, s.JIRA_TRANSITION_APPROVE, s.JIRA_TRANSITION_REJECT]):
        warns.append("All JIRA_TRANSITION_* empty — Jira issue status will never transition (was dead code before fix)")
    return warns


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
    # Only include jira; azure_devops and teams have been removed
    jira_info = services.get("jira")
    return HealthResponse(
        status="ok",
        service=settings.APP_NAME,
        environment=settings.APP_ENV,
        jira=jira_info,
    )
