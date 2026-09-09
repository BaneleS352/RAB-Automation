"""Demo endpoints — trigger live Jira-backed RAB scenarios."""

import logging

from fastapi import APIRouter, Form, HTTPException, Request

from app.services.dummy_flow import DummyFlowService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo", tags=["demo"])


def _require_demo(request: Request) -> None:
    settings = request.app.state.settings
    enabled = settings.feature_enabled(getattr(settings, "ENABLE_DEMO"))
    if not enabled:
        raise HTTPException(status_code=403, detail="Demo disabled in this environment")


@router.post("/flow")
async def run_demo_flow(
    request: Request,
    issue_key: str = Form(""),
    summary: str = Form("Demo release ticket"),
    needs_meeting: bool = Form(False),
    reject: bool = Form(False),
) -> dict:
    """Run a live Jira-backed SDL → SDM approval flow and return the step log."""
    _require_demo(request)
    try:
        service = DummyFlowService(issue_key=issue_key, summary=summary)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if reject:
        result = await service.run_rejection()
    else:
        result = await service.run_full_approval(needs_meeting=needs_meeting)
    # Same ledger as the dashboard Demo Lab so runs show in Webhook Activity.
    from app.api.dashboard import record_demo_ledger_event
    await record_demo_ledger_event(result.issue_key, "rejected" if reject else "full_approval", result.status)
    return {
        "issue_key": result.issue_key,
        "status": result.status,
        "steps": result.steps,
    }
