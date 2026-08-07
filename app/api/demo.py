"""Demo endpoints — trigger a simulated RAB approval flow for testing/logs."""

import logging

from fastapi import APIRouter, Query

from app.services.dummy_flow import DummyFlowService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo", tags=["demo"])


@router.get("/flow")
async def run_demo_flow(
    issue_key: str = Query("DEMO-1"),
    summary: str = Query("Demo release ticket"),
    needs_meeting: bool = Query(False),
    reject: bool = Query(False),
) -> dict:
    """Run a full simulated SDL → SDM approval flow and return the step log."""
    service = DummyFlowService(issue_key=issue_key, summary=summary)
    if reject:
        result = await service.run_rejection()
    else:
        result = await service.run_full_approval(needs_meeting=needs_meeting)
    return {
        "issue_key": result.issue_key,
        "status": result.status,
        "steps": result.steps,
    }