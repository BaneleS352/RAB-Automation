"""Dashboard HTML views for health and audit records."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.repositories.rab_repository import RabRepository
from app.services.jira_client import JiraClient
from app.services.azure_devops_client import AzureDevOpsClient
from app.services.teams_client import TeamsClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

templates = Jinja2Templates(directory="app/templates")

_repo = RabRepository()
_jira = JiraClient()
_azure = AzureDevOpsClient()
_teams = TeamsClient()


@router.get("/health", response_class=HTMLResponse)
async def dashboard_health(request: Request):
    jira_ok = await _jira.check_connection()
    azure_ok = await _azure.check_connection()
    teams_ok = await _teams.check_connection()

    services = {
        "jira": {"connected": jira_ok, "details": "Jira Cloud API" if jira_ok else "Not connected or unconfigured"},
        "azure_devops": {"connected": azure_ok, "details": "Azure DevOps API" if azure_ok else "Not connected or unconfigured"},
        "teams": {"connected": teams_ok, "details": "Microsoft Teams Bot Framework" if teams_ok else "Not connected or unconfigured"},
    }

    return templates.TemplateResponse(request, "health.html", {"services": services})


@router.get("/records", response_class=HTMLResponse)
async def dashboard_records(request: Request):
    records = await _repo.get_all_records(limit=100)
    return templates.TemplateResponse(request, "records.html", {"records": records})
