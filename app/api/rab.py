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


@router.get("/records", response_model=RabRecordList)
async def list_records(
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> RabRecordList:
    rows, total = await _repo.get_all_records_with_count(limit=limit, offset=offset)
    return RabRecordList(records=[RabRecord(**r) for r in rows], total=total)


@router.get("/records/{issue_key}", response_model=RabRecord | None)
async def get_record(issue_key: str) -> RabRecord | None:
    row = await _repo.get_record(issue_key)
    if row:
        return RabRecord(**row)
    return None
