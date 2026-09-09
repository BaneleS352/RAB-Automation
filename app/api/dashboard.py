"""Dashboard HTML views for health, audit records, webhooks, metrics, and demo."""

import asyncio
import logging
from pathlib import Path

import re as _re

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.metrics import get_metrics_data
from app.repositories.rab_repository import RabRepository
from app.services import health_check as _health_check_mod
from app.services.dummy_flow import DummyFlowService
from app.services.test_runner import run_test_suite, TestRunResult
from app.services.status_codes import KNOWN_STATUSES as STATUS_CODE_KNOWN_STATUSES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_templates_dir = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


def status_badge(value: object) -> str:
    """Normalize any workflow status/action/result string to a styled badge class.

    Templates used to interpolate raw status text (e.g. ``badge-{{ e.status }}``),
    which breaks for free-form orchestration results like
    ``"validation_failed: Missing …"`` (spaces/colons are not valid class tokens)
    and silently renders unstyled for values with no matching selector
    (``pending``, ``approve``, ``received`` …). Always returns a class defined
    in ``style.css`` (both themes); unknown values fall back to ``badge-none``.
    """
    v = _re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    if not v:
        return "badge-none"
    side = "sdl" if "sdl" in v else "sdm" if "sdm" in v else ""
    if "validated_with_notes" in v:
        return "badge-validated-with-notes"
    if "validation_failed" in v or "fail" in v:
        return "badge-validation_failed"
    if "reject" in v:
        return f"badge-{side}-rejected" if side else "badge-rejected"
    # NOTE: "request" is checked before "approv" so "approval_requested_sdl"
    # maps to requested, not approved.
    if "request" in v or "pending" in v or "progress" in v:
        return f"badge-{side}-requested" if side else "badge-pending"
    if "approv" in v:
        return f"badge-{side}-approved" if side else "badge-approved"
    if "release_ready" in v or v == "ready":
        return "badge-release-ready"
    if "meeting" in v:
        return "badge-meeting-scheduled"
    if "validat" in v:
        return "badge-validated"
    if "error" in v:
        return "badge-error"
    return "badge-none"


templates.env.filters["status_badge"] = status_badge

_repo = RabRepository()
# NOTE: JiraClient is constructed per request (not at import) so credential
# changes take effect without a restart. Do not add a module-level singleton here.

_RECORDS_PAGE_SIZE = 25
_WEBHOOK_PAGE_SIZE = 50

# Shared cache lives in app.services.health_check (single live Jira check per
# TTL window across all routes). Aliased (same objects) so existing
# `from app.api.dashboard import _health_cache` references keep working.
_HEALTH_CACHE_TTL = _health_check_mod._HEALTH_CACHE_TTL
_health_cache = _health_check_mod._health_cache
_health_lock = _health_check_mod._health_lock

_test_run_lock = asyncio.Lock()
_last_test_result: TestRunResult | None = None


def _require_feature(request: Request, feature: str) -> None:
    settings = request.app.state.settings
    enabled = settings.feature_enabled(getattr(settings, feature))
    if not enabled:
        raise HTTPException(status_code=403, detail="Forbidden")


def _require_real_jira(use_real_jira: bool) -> bool:
    """Unify the real-Jira gate for Demo Lab and Tools.

    Returns the effective flag. Raises 503 when real Jira is requested but
    credentials are missing, so both entry points behave identically (previously
    Demo returned 503 while Tools raised an unhandled 500).
    """
    from app.config import get_settings
    s = get_settings()
    real_available = bool(s.JIRA_BASE_URL and s.JIRA_EMAIL and s.JIRA_API_TOKEN)
    if use_real_jira and not real_available:
        raise HTTPException(status_code=503, detail="Real Jira requested but Jira credentials are not configured")
    return bool(use_real_jira and real_available)


# Scenario name → DummyFlowService method. Single dispatch table shared by the
# Tools and Demo handlers so new scenarios are added in one place (previously
# two parallel if/elif chains that already drifted once).
_SCENARIO_METHODS = {
    "pending_sdl": "run_pending_sdl",
    "pending_sdm": "run_pending_sdm",
    "validation_failed": "run_validation_failed",
    "validated_with_notes": "run_validated_with_notes",
    "rejected_sdl": "run_rejection",
    "rejected_sdm": "run_sdm_rejection",
    "aging": "run_aging_pending",
}


async def _run_demo_scenario(svc, scenario: str, *, needs_meeting: bool = False, reject: bool = False):
    """Run one named demo scenario (or the default full flow) on a DummyFlowService."""
    if scenario == "full" or not scenario:
        return await svc.run_full_approval(needs_meeting=needs_meeting)
    method_name = _SCENARIO_METHODS.get(scenario)
    if method_name is None:
        # Unknown scenario values fall back to legacy behavior, never 500.
        return await svc.run_rejection() if reject else await svc.run_full_approval(needs_meeting=needs_meeting)
    method = getattr(svc, method_name)
    if scenario == "aging":
        return await method(days=3)
    return await method()


async def record_demo_ledger_event(issue_key: str, scenario: str, fallback_status: str = "") -> None:
    """Write a synthetic ledger entry so Demo/Tools runs show in Webhook Activity.

    Real Jira deliveries arrive via POST /webhooks/jira; Demo Lab and Tools drive
    the orchestrator directly and previously left the ledger (and the Webhooks
    page) permanently empty. Entries use a `demo.*` event_type plus a `demo:`-
    prefixed random event_id so they read as synthetic and can never collide
    with real deliveries. Fire-and-forget: a ledger failure must never break a
    demo run, so all errors are swallowed to a warning.
    """
    import uuid as _uuid

    event_type = f"demo.{scenario or 'full_approval'}"
    event_id = f"demo:{issue_key}:{_uuid.uuid4().hex[:8]}"
    try:
        await _repo.record_webhook_event(event_id, issue_key, event_type)
        record = await _repo.get_record(issue_key)
        status = (record or {}).get("status") or fallback_status or "received"
        await _repo.update_webhook_event_status(event_id, status)
    except Exception:
        logger.warning("Demo ledger write failed for %s", issue_key, exc_info=True)


async def _check_connection_status() -> dict:
    """Connection status for Jira + Teams, cached to avoid hammering
    the external API on every page load / 30s auto-refresh.

    Delegates to the shared app.services.health_check cache so /health and the
    dashboard trigger at most one live Jira check per TTL window (previously
    each kept its own cache and each called Jira on a miss).
    """
    from app.services.health_check import get_service_statuses

    return await get_service_statuses()

_KNOWN_STATUSES: list[str] = STATUS_CODE_KNOWN_STATUSES


@router.get("/health", response_class=HTMLResponse)
async def dashboard_health(request: Request, aging_days: int = Query(2, ge=1)) -> HTMLResponse:
    services = await _check_connection_status()

    counts = await _repo.get_status_counts()
    pending = await _repo.get_pending_approval_count()
    in_approval = sum(counts.get(s, 0) for s in (
        "sdl_requested", "sdm_requested", "sdl_approved", "sdm_approved",
    ))
    kpis = {
        "total": sum(counts.values()),
        "validated": counts.get("validated", 0),
        "validated_with_notes": counts.get("validated_with_notes", 0),
        # NOTE: the pipeline rail below must stay a true partition of total.
        # Keep it status-based only: `pending_approval` is approval-column based
        # and overlaps status buckets (double-count), so the rail uses the
        # mutually exclusive `in_approval` (+ `pending`) instead. The KPI card
        # keeps `pending_approval` since aging uses the same definition.
        "in_approval": in_approval,
        "pending": counts.get("pending", 0),
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
        # Match the JSON API contract (GET /rab/records/{key} → 404) so
        # crawlers and monitors can distinguish missing issues.
        return templates.TemplateResponse(
            request, "record_detail.html", {"record": None, "events": [], "issue_key": issue_key},
            status_code=404,
        )
    events = await _repo.get_approval_events(issue_key)
    field_changes = await _repo.get_field_changes(issue_key)
    webhook_events = await _repo.get_webhook_events_by_issue(issue_key, limit=20)
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


@router.get("/tools", response_class=HTMLResponse)
async def dashboard_tools(request: Request) -> HTMLResponse:
    _require_feature(request, "ENABLE_DEMO")
    data = get_metrics_data()
    events = await _repo.get_webhook_events(limit=20)
    return templates.TemplateResponse(request, "tools.html", {"metrics": data, "events": events, "result": None})


@router.post("/tools", response_class=HTMLResponse)
async def dashboard_tools_run(
    request: Request,
    action: str = Form(""),
    issue_key: str = Form("DEMO-1"),
    summary: str = Form("Demo release ticket"),
    scenario: str = Form(""),
    needs_meeting: bool = Form(False),
    use_real_jira: bool = Form(False),
) -> HTMLResponse:
    _require_feature(request, "ENABLE_DEMO")
    data = get_metrics_data()
    events = await _repo.get_webhook_events(limit=20)
    result = None
    cleanup_result = None
    if action == "cleanup_demo":
        # Cleanup always targets live Jira by definition — require credentials.
        _require_real_jira(True)
        cleanup_result = await DummyFlowService.cleanup_demo_issues()
        events = await _repo.get_webhook_events(limit=20)
    elif action in ("pending_sdl", "pending_sdm", "validation_failed", "aging"):
        try:
            svc = DummyFlowService(issue_key=issue_key, summary=summary, use_real_jira=_require_real_jira(use_real_jira))
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if action == "pending_sdl":
            result = await svc.run_pending_sdl()
        elif action == "pending_sdm":
            result = await svc.run_pending_sdm()
        elif action == "validation_failed":
            result = await svc.run_validation_failed()
        elif action == "aging":
            result = await svc.run_aging_pending(days=3)
    elif action == "custom":
        try:
            svc = DummyFlowService(issue_key=issue_key, summary=summary, use_real_jira=_require_real_jira(use_real_jira))
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        result = await _run_demo_scenario(svc, scenario, needs_meeting=needs_meeting)
    if result is not None:
        scenario_name = action if action != "custom" else (scenario or "full_approval")
        await record_demo_ledger_event(issue_key, scenario_name, result.status)
        # Re-fetch so the just-written demo.* row is visible without a manual
        # refresh (events/data above are pre-run snapshots; cleanup branch already did this).
        events = await _repo.get_webhook_events(limit=20)
        data = get_metrics_data()
    return templates.TemplateResponse(request, "tools.html", {"metrics": data, "events": events, "result": result, "cleanup_result": cleanup_result})


@router.get("/demo", response_class=HTMLResponse)
async def dashboard_demo_form(
    request: Request,
    issue_key: str = Query("DEMO-1"),
    summary: str = Query("Demo release ticket"),
    needs_meeting: bool = Query(False),
    reject: bool = Query(False),
    scenario: str = Query(""),
    use_real_jira: bool = Query(False),
) -> HTMLResponse:
    """Render the demo approval flow form page. Now supports real Jira tickets (live) vs stub."""
    _require_feature(request, "ENABLE_DEMO")
    from app.config import get_settings
    s = get_settings()
    real_available = bool(s.JIRA_BASE_URL and s.JIRA_EMAIL and s.JIRA_API_TOKEN)
    return templates.TemplateResponse(
        request,
        "demo.html",
        {
            "result": None,
            "issue_key": issue_key,
            "summary": summary,
            "needs_meeting": needs_meeting,
            "reject": reject,
            "scenario": scenario,
            "use_real_jira": use_real_jira,
            "real_available": real_available,
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
    use_real_jira: bool = Form(False),
) -> HTMLResponse:
    """Run the demo approval flow and render the result. Real Jira mode creates live tickets."""
    _require_feature(request, "ENABLE_DEMO")
    from app.config import get_settings
    s = get_settings()
    real_available = bool(s.JIRA_BASE_URL and s.JIRA_EMAIL and s.JIRA_API_TOKEN)
    eff_real = _require_real_jira(use_real_jira)
    try:
        service = DummyFlowService(issue_key=issue_key, summary=summary, use_real_jira=eff_real)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    # Scenario takes precedence over legacy reject/needs_meeting flags
    result = await _run_demo_scenario(service, scenario, needs_meeting=needs_meeting, reject=reject)
    await record_demo_ledger_event(issue_key, scenario or "full_approval", result.status)
    return templates.TemplateResponse(
        request,
        "demo.html",
        {
            "result": result,
            "issue_key": issue_key,
            "summary": summary,
            "needs_meeting": needs_meeting,
            "reject": reject,
            "scenario": scenario,
            "use_real_jira": use_real_jira,
            "real_available": real_available,
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
    """Run the pytest suite with token gating and single-flight lock.

    NOTE (proxy timeouts): the suite runs inline, up to run_test_suite's
    timeout (default 120s). If a reverse proxy times out first (e.g. nginx
    default 60s), the client sees a 504 but the run continues server-side;
    retrying is safe — the single-flight lock returns the "already in
    progress" notice instead of starting a duplicate run. Keep any proxy
    read-timeout above the suite timeout, or accept the notice-based retry.
    """
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
