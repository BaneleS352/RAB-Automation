"""Dashboard HTML views for health and audit records."""

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.repositories.rab_repository import RabRepository
from app.services.jira_client import JiraClient
from app.services.azure_devops_client import AzureDevOpsClient
from app.services.teams_client import TeamsClient
from app.services.test_runner import run_test_suite

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_templates_dir = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

_repo = RabRepository()
_jira = JiraClient()
_azure = AzureDevOpsClient()
_teams = TeamsClient()


@router.get("/health", response_class=HTMLResponse)
async def dashboard_health(request: Request) -> HTMLResponse:
    jira_status = await _jira.check_connection()
    azure_status = await _azure.check_connection()
    teams_status = await _teams.check_connection()

    services = {
        "jira": {"connected": jira_status.get("connected", False), "details": jira_status.get("details", "Unknown")},
        "azure_devops": {"connected": azure_status.get("connected", False), "details": azure_status.get("details", "Unknown")},
        "teams": {"connected": teams_status.get("connected", False), "details": teams_status.get("details", "Unknown")},
    }

    return templates.TemplateResponse(request, "health.html", {"services": services})


@router.get("/records", response_class=HTMLResponse)
async def dashboard_records(request: Request) -> HTMLResponse:
    records = await _repo.get_all_records(limit=50)
    return templates.TemplateResponse(request, "records.html", {"records": records})


@router.get("/test", response_class=HTMLResponse)
async def dashboard_test(request: Request) -> HTMLResponse:
    result = await run_test_suite()
    return templates.TemplateResponse(request, "test.html", {"result": result})
