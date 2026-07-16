"""Health and root endpoints."""

import logging

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


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings

    jira_status = await jira_client.check_connection()
    azure_status = await azure_client.check_connection()
    teams_status = await teams_client.check_connection()

    return HealthResponse(
        status="ok",
        service=settings.APP_NAME,
        environment=settings.APP_ENV,
        jira=JiraConnectionInfo(connected=jira_status["connected"], details=jira_status["details"]),
        azure_devops=JiraConnectionInfo(connected=azure_status["connected"], details=azure_status["details"]),
        teams=JiraConnectionInfo(connected=teams_status["connected"], details=teams_status["details"]),
    )
