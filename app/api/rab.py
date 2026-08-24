"""RAB records API endpoints – query audit trail."""

import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.repositories.rab_repository import RabRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/rab", tags=["rab"])

_repo = RabRepository()

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


class RabRecord(BaseModel):
    id: int
    issue_key: str
    summary: str
    status: str
    validation_result: str
    sdl_approval: str
    sdm_approval: str
    rejection_reason: str
    rejected_by: str
    meeting_needed: int
    created_at: str
    updated_at: str


class RabRecordList(BaseModel):
    records: list[RabRecord]
    total: int


class ApprovalEvent(BaseModel):
    id: int
    issue_key: str
    step: str
    action: str
    approver: str
    reason: str
    created_at: str


class WebhookEvent(BaseModel):
    id: int
    event_id: str
    issue_key: str
    event_type: str
    status: str
    created_at: str


class WebhookEventList(BaseModel):
    events: list[WebhookEvent]
    total: int


class RabSummary(BaseModel):
    total: int
    counts: dict[str, int]
    pending_approval: int
    validation_failed: int
    rejected: int
    release_ready: int
    meeting_scheduled: int
    aging: list[RabRecord]


@router.get("/records", response_model=RabRecordList)
async def list_records(
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    status: str = Query(""),
    q: str = Query(""),
) -> RabRecordList:
    rows, total = await _repo.get_all_records_with_count(limit=limit, offset=offset, status=status, q=q)
    return RabRecordList(records=[RabRecord(**r) for r in rows], total=total)


@router.get("/records/{issue_key}", response_model=RabRecord | None)
async def get_record(issue_key: str) -> RabRecord | None:
    row = await _repo.get_record(issue_key)
    if row:
        return RabRecord(**row)
    return None


@router.get("/records/{issue_key}/events", response_model=list[ApprovalEvent])
async def get_record_events(issue_key: str) -> list[ApprovalEvent]:
    rows = await _repo.get_approval_events(issue_key)
    return [ApprovalEvent(**r) for r in rows]


@router.get("/webhook-events", response_model=WebhookEventList)
async def list_webhook_events(
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> WebhookEventList:
    events, total = await _repo.get_webhook_events_with_count(limit=limit, offset=offset)
    return WebhookEventList(events=[WebhookEvent(**e) for e in events], total=total)


@router.get("/summary", response_model=RabSummary)
async def get_summary(aging_days: int = Query(2, ge=1)) -> RabSummary:
    counts = await _repo.get_status_counts()
    pending = await _repo.get_pending_approval_count()
    aging = await _repo.get_aging_records(days=aging_days)
    return RabSummary(
        total=sum(counts.values()),
        counts=counts,
        pending_approval=pending,
        validation_failed=counts.get("validation_failed", 0),
        rejected=counts.get("sdl_rejected", 0) + counts.get("sdm_rejected", 0),
        release_ready=counts.get("release_ready", 0),
        meeting_scheduled=counts.get("meeting_scheduled", 0),
        aging=[RabRecord(**r) for r in aging],
    )


@router.post("/sync")
async def sync_jira(project_key: str | None = None) -> dict:
    """Sync all Jira issues for project into local monitor (regardless of creation method)."""
    from app.services.jira_sync import JiraSyncService

    service = JiraSyncService()
    result = await service.sync_project(project_key) if project_key else await service.sync_all()
    return {
        "synced": result.synced,
        "created": result.created,
        "updated": result.updated,
        "failed": result.failed,
        "errors": result.errors[:5],
    }
