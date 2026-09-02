"""RAB records API endpoints – query audit trail."""

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.repositories.rab_repository import RabRepository
from app.services.jira_client import JiraClient

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
    creator: str = ""
    assignee: str = ""
    # Rich fields — previously blank in UI because they were never persisted
    description: str = ""
    priority: str = ""
    issuetype: str = ""
    jira_status: str = ""
    labels: str = ""
    reporter: str = ""
    jira_updated: str = ""
    raw_fields: str = ""
    deployment_instructions: str = ""
    outcome_notes: str = ""
    rollback_strategy: str = ""
    mitigation_strategy: str = ""
    related_release_reference: str = ""
    release_outcome: str = ""
    environments: str = ""
    development: str = ""
    parent_reference: str = ""
    sprint: str = ""
    jira_exists: int = 1
    jira_last_seen: str = ""


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


class FieldChangeEvent(BaseModel):
    id: int
    issue_key: str
    field: str
    from_value: str
    to_value: str
    author: str
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
    validated_with_notes: int
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


@router.get("/records/{issue_key}", response_model=RabRecord)
async def get_record(issue_key: str) -> RabRecord:
    row = await _repo.get_record(issue_key)
    if row:
        return RabRecord(**row)
    raise HTTPException(status_code=404, detail=f"Issue {issue_key} not found")


@router.get("/records/{issue_key}/events", response_model=list[ApprovalEvent])
async def get_record_events(issue_key: str) -> list[ApprovalEvent]:
    rows = await _repo.get_approval_events(issue_key)
    return [ApprovalEvent(**r) for r in rows]


@router.get("/records/{issue_key}/changes", response_model=list[FieldChangeEvent])
async def get_record_changes(issue_key: str) -> list[FieldChangeEvent]:
    rows = await _repo.get_field_changes(issue_key)
    return [FieldChangeEvent(**r) for r in rows]


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
        validated_with_notes=counts.get("validated_with_notes", 0),
        rejected=counts.get("sdl_rejected", 0) + counts.get("sdm_rejected", 0),
        release_ready=counts.get("release_ready", 0),
        meeting_scheduled=counts.get("meeting_scheduled", 0),
        aging=[RabRecord(**r) for r in aging],
    )


@router.get("/live")
async def live_jira_feed(project_key: str | None = None, limit: int = Query(20, ge=1, le=50)) -> dict:
    """Live Jira feed — directly from Jira REST, not from local DB. Powers the live dashboard."""
    jira = JiraClient()
    if not jira.base_url or not jira.email or not jira.api_token:
        return {"live": False, "issues": [], "detail": "Jira not configured"}
    # Prefer explicit project, else configured JIRA_PROJECT_KEY, else all-recent
    key = project_key or jira.settings.JIRA_PROJECT_KEY
    try:
        if key:
            issues = await jira.list_project_issues(key, max_results=100)
            # Live Jira is the source of truth. Reconcile only the configured
            # project so historical local records can be labeled as removed.
            await _repo.mark_missing_from_jira(key, {it.get("key") for it in issues if it.get("key")})
            for it in issues:
                if it.get("key"):
                    await _repo.mark_jira_seen(it["key"])
        else:
            data = await jira.search_issues("ORDER BY updated DESC", max_results=limit)
            issues = data.get("issues", [])
        # Return trimmed live view
        live_issues = []
        for it in issues[:limit]:
            f = it.get("fields", {})
            live_issues.append({
                "key": it.get("key"),
                "summary": f.get("summary", ""),
                "status": (f.get("status") or {}).get("name", ""),
                "assignee": (f.get("assignee") or {}).get("displayName", ""),
                "updated": f.get("updated", ""),
                "priority": (f.get("priority") or {}).get("name", ""),
            })
        return {"live": True, "project": key or "all", "issues": live_issues, "count": len(live_issues)}
    except Exception as e:
        logger.warning("Live Jira feed failed: %s", e)
        return {"live": False, "issues": [], "detail": str(e)[:200]}


