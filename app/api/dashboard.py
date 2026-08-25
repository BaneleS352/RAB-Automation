"""Dashboard HTML views for health, audit records, webhooks, metrics, and demo."""

import asyncio
import logging
import time
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.metrics import get_metrics_data
from app.repositories.rab_repository import RabRepository
from app.services.dummy_flow import DummyFlowService
from app.services.jira_client import JiraClient
from app.services.test_runner import run_test_suite, TestRunResult
from app.services.status_codes import KNOWN_STATUSES as STATUS_CODE_KNOWN_STATUSES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_templates_dir = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

_repo = RabRepository()
_jira = JiraClient()

_RECORDS_PAGE_SIZE = 25
_WEBHOOK_PAGE_SIZE = 50

_HEALTH_CACHE_TTL = 30.0
_health_cache: dict = {"at": 0.0, "services": None}
_health_lock = asyncio.Lock()

_test_run_lock = asyncio.Lock()
_last_test_result: TestRunResult | None = None


def _require_feature(request: Request, feature: str) -> None:
    settings = request.app.state.settings
    enabled = settings.feature_enabled(getattr(settings, feature))
    if not enabled:
        raise HTTPException(status_code=403, detail="Forbidden")


async def _check_connection_status() -> dict:
    """Connection status for Jira, cached to avoid hammering
    the external API on every page load / 30s auto-refresh."""
    now = time.monotonic()
    if _health_cache["services"] is not None and now - _health_cache["at"] < _HEALTH_CACHE_TTL:
        return _health_cache["services"]

    async with _health_lock:
        # Double-check after acquiring lock
        now = time.monotonic()
        if _health_cache["services"] is not None and now - _health_cache["at"] < _HEALTH_CACHE_TTL:
            return _health_cache["services"]
        jira_status = await _jira.check_connection()

        services = {
            "jira": {"connected": jira_status.get("connected", False), "details": jira_status.get("details", "Unknown")},
        }
        _health_cache["at"] = now
        _health_cache["services"] = services
        return services

_KNOWN_STATUSES: list[str] = STATUS_CODE_KNOWN_STATUSES


@router.get("/health", response_class=HTMLResponse)
async def dashboard_health(request: Request, aging_days: int = Query(2, ge=1)) -> HTMLResponse:
    services = await _check_connection_status()

    counts = await _repo.get_status_counts()
    pending = await _repo.get_pending_approval_count()
    kpis = {
        "total": sum(counts.values()),
        "validated": counts.get("validated", 0),
        "pending_approval": pending,
        "release_ready": counts.get("release_ready", 0),
        "meeting_scheduled": counts.get("meeting_scheduled", 0),
        "validation_failed": counts.get("validation_failed", 0),
        "rejected": counts.get("sdl_rejected", 0) + counts.get("sdm_rejected", 0),
    }
    aging = await _repo.get_aging_records(days=aging_days)
    failures = await _repo.get_recent_failures(limit=5)

    return templates.TemplateResponse(
        request,
        "health.html",
        {
            "services": services,
            "kpis": kpis,
            "aging": aging,
            "failures": failures,
            "aging_days": aging_days,
        },
    )


@router.get("/records", response_class=HTMLResponse)
async def dashboard_records(
    request: Request,
    status: str = Query(""),
    q: str = Query(""),
    offset: int = Query(0, ge=0),
) -> HTMLResponse:
    limit = _RECORDS_PAGE_SIZE
    records, total = await _repo.get_all_records_with_count(
        limit=limit, offset=offset, status=status, q=q,
    )
    return templates.TemplateResponse(
        request,
        "records.html",
        {
            "records": records,
            "total": total,
            "offset": offset,
            "limit": limit,
            "status": status,
            "q": q,
            "statuses": _KNOWN_STATUSES,
        },
    )


@router.get("/records/{issue_key}", response_class=HTMLResponse)
async def dashboard_record_detail(request: Request, issue_key: str) -> HTMLResponse:
    record = await _repo.get_record(issue_key)
    if not record:
        return templates.TemplateResponse(
            request, "record_detail.html", {"record": None, "events": [], "issue_key": issue_key},
        )
    events = await _repo.get_approval_events(issue_key)
    field_changes = await _repo.get_field_changes(issue_key)
    webhook_events = [e for e in await _repo.get_webhook_events(limit=100) if e.get("issue_key") == issue_key]
    return templates.TemplateResponse(
        request, "record_detail.html", {"record": record, "events": events, "field_changes": field_changes, "webhook_events": webhook_events, "issue_key": issue_key},
    )


@router.get("/webhooks", response_class=HTMLResponse)
async def dashboard_webhooks(request: Request) -> HTMLResponse:
    events = await _repo.get_webhook_events(limit=_WEBHOOK_PAGE_SIZE)
    return templates.TemplateResponse(request, "webhooks.html", {"events": events})


@router.get("/metrics", response_class=HTMLResponse)
async def dashboard_metrics(request: Request) -> HTMLResponse:
    data = get_metrics_data()
    return templates.TemplateResponse(request, "metrics.html", {"metrics": data})


@router.get("/sync", response_class=HTMLResponse)
async def dashboard_sync_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "sync.html", {"result": None})


@router.post("/sync", response_class=HTMLResponse)
async def dashboard_sync_run(request: Request) -> HTMLResponse:
    from app.services.jira_sync import JiraSyncService

    service = JiraSyncService()
    result = await service.sync_all()
    counts = await _repo.get_status_counts()
    total = sum(counts.values())
    return templates.TemplateResponse(request, "sync.html", {"result": result, "total": total})


@router.get("/tools", response_class=HTMLResponse)
async def dashboard_tools(request: Request) -> HTMLResponse:
    _require_feature(request, "ENABLE_DEMO")
    data = get_metrics_data()
    events = await _repo.get_webhook_events(limit=20)
    return templates.TemplateResponse(request, "tools.html", {"metrics": data, "events": events, "result": None, "seed_results": None, "sync_result": None})


@router.post("/tools", response_class=HTMLResponse)
async def dashboard_tools_run(
    request: Request,
    action: str = Form(""),
    issue_key: str = Form("DEMO-1"),
    summary: str = Form("Demo release ticket"),
    scenario: str = Form(""),
    needs_meeting: bool = Form(False),
) -> HTMLResponse:
    _require_feature(request, "ENABLE_DEMO")
    data = get_metrics_data()
    events = await _repo.get_webhook_events(limit=20)
    result = None
    seed_results = None
    sync_result = None
    # Sync
    if action == "sync":
        from app.services.jira_sync import JiraSyncService
        sync_result = await JiraSyncService().sync_all()
        events = await _repo.get_webhook_events(limit=20)
    # Demo seed
    elif action == "seed":
        seed_results = await DummyFlowService.seed_demo_dataset()
        events = await _repo.get_webhook_events(limit=20)
    # Demo single scenarios
    elif action in ("pending_sdl", "pending_sdm", "validation_failed", "aging"):
        svc = DummyFlowService(issue_key=issue_key, summary=summary)
        if action == "pending_sdl":
            result = await svc.run_pending_sdl()
        elif action == "pending_sdm":
            result = await svc.run_pending_sdm()
        elif action == "validation_failed":
            result = await svc.run_validation_failed()
        elif action == "aging":
            result = await svc.run_aging_pending(days=3)
    elif action == "custom":
        svc = DummyFlowService(issue_key=issue_key, summary=summary)
        if scenario == "pending_sdl":
            result = await svc.run_pending_sdl()
        elif scenario == "pending_sdm":
            result = await svc.run_pending_sdm()
        elif scenario == "validation_failed":
            result = await svc.run_validation_failed()
        elif scenario == "rejected_sdl":
            result = await svc.run_rejection()
        elif scenario == "rejected_sdm":
            result = await svc.run_sdm_rejection()
        elif scenario == "aging":
            result = await svc.run_aging_pending(days=3)
        else:
            result = await svc.run_full_approval(needs_meeting=needs_meeting)
    return templates.TemplateResponse(request, "tools.html", {"metrics": data, "events": events, "result": result, "seed_results": seed_results, "sync_result": sync_result})


@router.get("/demo", response_class=HTMLResponse)
async def dashboard_demo_form(
    request: Request,
    issue_key: str = Query("DEMO-1"),
    summary: str = Query("Demo release ticket"),
    needs_meeting: bool = Query(False),
    reject: bool = Query(False),
    scenario: str = Query(""),
) -> HTMLResponse:
    """Render the demo approval flow form page."""
    _require_feature(request, "ENABLE_DEMO")
    # Seed dataset via GET for convenience: /dashboard/demo?scenario=seed
    seed_results = None
    if scenario == "seed":
        seed_results = []  # populated on POST; GET just shows CTA
    return templates.TemplateResponse(
        request,
        "demo.html",
        {
            "result": None,
            "seed_results": seed_results,
            "issue_key": issue_key,
            "summary": summary,
            "needs_meeting": needs_meeting,
            "reject": reject,
            "scenario": scenario,
        },
    )


@router.post("/demo", response_class=HTMLResponse)
async def dashboard_demo_run(
    request: Request,
    issue_key: str = Form("DEMO-1"),
    summary: str = Form("Demo release ticket"),
    needs_meeting: bool = Form(False),
    reject: bool = Form(False),
    scenario: str = Form(""),
) -> HTMLResponse:
    """Run the demo approval flow and render the result."""
    _require_feature(request, "ENABLE_DEMO")
    # Seed full dataset
    if scenario == "seed":
        results = await DummyFlowService.seed_demo_dataset()
        return templates.TemplateResponse(
            request,
            "demo.html",
            {
                "result": None,
                "seed_results": results,
                "issue_key": issue_key,
                "summary": summary,
                "needs_meeting": needs_meeting,
                "reject": reject,
                "scenario": scenario,
            },
        )
    service = DummyFlowService(issue_key=issue_key, summary=summary)
    # Scenario takes precedence over legacy reject/needs_meeting flags
    if scenario == "pending_sdl":
        result = await service.run_pending_sdl()
    elif scenario == "pending_sdm":
        result = await service.run_pending_sdm()
    elif scenario == "validation_failed":
        result = await service.run_validation_failed()
    elif scenario == "rejected_sdl":
        result = await service.run_rejection()
    elif scenario == "rejected_sdm":
        result = await service.run_sdm_rejection()
    elif scenario == "aging":
        result = await service.run_aging_pending(days=3)
    elif scenario == "full":
        result = await service.run_full_approval(needs_meeting=needs_meeting)
    else:
        result = await service.run_rejection() if reject else await service.run_full_approval(needs_meeting=needs_meeting)
    return templates.TemplateResponse(
        request,
        "demo.html",
        {
            "result": result,
            "seed_results": None,
            "issue_key": issue_key,
            "summary": summary,
            "needs_meeting": needs_meeting,
            "reject": reject,
            "scenario": scenario,
        },
    )


@router.get("/test", response_class=HTMLResponse)
async def dashboard_test_form(request: Request) -> HTMLResponse:
    """Render the test results page (last run result or empty state)."""
    _require_feature(request, "ENABLE_TEST_UI")
    global _last_test_result
    return templates.TemplateResponse(
        request,
        "test.html",
        {"result": _last_test_result, "notice": ""},
    )


@router.post("/test", response_class=HTMLResponse)
async def dashboard_test(request: Request) -> HTMLResponse:
    """Run the pytest suite with token gating and single-flight lock."""
    _require_feature(request, "ENABLE_TEST_UI")
    global _last_test_result
    from app.config import get_settings
    from app.api.auth import AccessTokenMiddleware

    token = get_settings().ACCESS_TOKEN
    if token and AccessTokenMiddleware._token_from(request) != token:
        return HTMLResponse("Unauthorized", status_code=401)
    if _test_run_lock.locked():
        return templates.TemplateResponse(
            request,
            "test.html",
            {"result": _last_test_result, "notice": "A test run is already in progress. Please wait."},
        )
    async with _test_run_lock:
        _last_test_result = await run_test_suite()
    return templates.TemplateResponse(request, "test.html", {"result": _last_test_result, "notice": ""})
