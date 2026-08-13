"""Health and root endpoints."""

import logging
import time

from fastapi import APIRouter, Request

from app.models.responses import HealthResponse, JiraConnectionInfo
from app.services.azure_devops_client import AzureDevOpsClient
from app.services.jira_client import JiraClient
from app.services.teams_client import TeamsClient

logger = logging.getLogger(__name__)

router = APIRouter()

jira_client = JiraClient()
azure_client = AzureDevOpsClient()
teams_client = TeamsClient()

_HEALTH_CACHE_TTL = 30.0
_health_cache: dict = {"at": 0.0, "services": None}


async def _check_services() -> dict:
    """Connection status for the three integrations, cached to avoid hammering
    the external APIs on every health-scraper request."""
    now = time.monotonic()
    if _health_cache["services"] is not None and now - _health_cache["at"] < _HEALTH_CACHE_TTL:
        return _health_cache["services"]

    jira_status = await jira_client.check_connection()
    azure_status = await azure_client.check_connection()
    teams_status = await teams_client.check_connection()

    services = {
        "jira": JiraConnectionInfo(connected=jira_status["connected"], details=jira_status["details"]),
        "azure_devops": JiraConnectionInfo(connected=azure_status["connected"], details=azure_status["details"]),
        "teams": JiraConnectionInfo(connected=teams_status["connected"], details=teams_status["details"]),
    }
    _health_cache["at"] = now
    _health_cache["services"] = services
    return services


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    services = await _check_services()
    return HealthResponse(
        status="ok",
        service=settings.APP_NAME,
        environment=settings.APP_ENV,
        **services,
    )
