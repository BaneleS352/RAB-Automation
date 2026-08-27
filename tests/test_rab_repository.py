"""Tests for the RabRepository."""

import pytest

from app.repositories.rab_repository import RabRepository


@pytest.fixture()
def repo() -> RabRepository:
    return RabRepository()


@pytest.mark.asyncio
async def test_record_validation_passed(repo: RabRepository) -> None:
    await repo.record_validation("REPO-1", True, "All good")
    record = await repo.get_record("REPO-1")
    assert record is not None
    assert record["issue_key"] == "REPO-1"
    assert record["status"] == "validated"
    assert record["validation_result"] == "All good"


@pytest.mark.asyncio
async def test_record_validation_failed(repo: RabRepository) -> None:
    await repo.record_validation("REPO-2", False, "Missing fields")
    record = await repo.get_record("REPO-2")
    assert record is not None
    assert record["status"] == "validation_failed"


@pytest.mark.asyncio
async def test_upsert_record_creates_new(repo: RabRepository) -> None:
    row_id = await repo.upsert_record("REPO-3", {
        "issue_key": "REPO-3", "summary": "Test", "status": "pending",
    })
    assert row_id > 0


@pytest.mark.asyncio
async def test_upsert_record_updates_existing(repo: RabRepository) -> None:
    await repo.upsert_record("REPO-4", {
        "issue_key": "REPO-4", "summary": "Original", "status": "pending",
    })
    await repo.upsert_record("REPO-4", {
        "issue_key": "REPO-4", "summary": "Updated", "status": "validated",
    })
    record = await repo.get_record("REPO-4")
    assert record["summary"] == "Updated"
    assert record["status"] == "validated"


@pytest.mark.asyncio
async def test_record_approval_event(repo: RabRepository) -> None:
    await repo.record_validation("REPO-5", True, "OK")
    await repo.record_approval_event("REPO-5", "SDL", "approve", "Manager", "Looks good")
    record = await repo.get_record("REPO-5")
    assert record["sdl_approval"] == "approved"
    events = await repo.get_approval_events("REPO-5")
    assert len(events) == 1
    assert events[0]["step"] == "SDL"
    assert events[0]["action"] == "approve"
    assert events[0]["approver"] == "Manager"


@pytest.mark.asyncio
async def test_record_approval_rejection(repo: RabRepository) -> None:
    await repo.record_validation("REPO-6", True, "OK")
    await repo.record_approval_event("REPO-6", "SDL", "reject", "Manager", "Not ready")
    record = await repo.get_record("REPO-6")
    assert record["sdl_approval"] == "rejected"
    assert record["rejection_reason"] == "Not ready"
    assert record["rejected_by"] == "Manager"


@pytest.mark.asyncio
async def test_approval_events_multiple(repo: RabRepository) -> None:
    await repo.record_validation("REPO-7", True, "OK")
    await repo.record_approval_event("REPO-7", "SDL", "approve", "Alice")
    await repo.record_approval_event("REPO-7", "SDM", "approve", "Bob")
    events = await repo.get_approval_events("REPO-7")
    assert len(events) == 2
    assert events[0]["step"] == "SDL"
    assert events[1]["step"] == "SDM"


@pytest.mark.asyncio
async def test_get_record_returns_none(repo: RabRepository) -> None:
    record = await repo.get_record("NONEXISTENT")
    assert record is None


@pytest.mark.asyncio
async def test_approval_events_empty(repo: RabRepository) -> None:
    events = await repo.get_approval_events("NO-EVENTS")
    assert events == []


@pytest.mark.asyncio
async def test_record_webhook_event_new(repo: RabRepository) -> None:
    result = await repo.record_webhook_event("wh-unique", "TEST-KEY", "jira:issue_created")
    assert result is True


@pytest.mark.asyncio
async def test_record_webhook_event_duplicate(repo: RabRepository) -> None:
    await repo.record_webhook_event("wh-dup", "TEST-KEY", "jira:issue_created")
    result = await repo.record_webhook_event("wh-dup", "TEST-KEY", "jira:issue_created")
    assert result is False


@pytest.mark.asyncio
async def test_get_pending_approval_count_counts_requested_columns(repo: RabRepository) -> None:
    before = await repo.get_pending_approval_count()
    await repo.upsert_record("PEND-1", {"issue_key": "PEND-1", "sdl_approval": "requested", "status": "sdl_requested"})
    await repo.upsert_record("PEND-2", {"issue_key": "PEND-2", "sdm_approval": "requested", "status": "sdm_requested"})
    await repo.record_validation("PEND-3", True, "OK")
    assert await repo.get_pending_approval_count() == before + 2


@pytest.mark.asyncio
async def test_get_aging_records_uses_column_condition(repo: RabRepository) -> None:
    from app.database import get_db

    await repo.upsert_record("AGE-1", {"issue_key": "AGE-1", "status": "sdl_requested", "sdl_approval": "pending"})
    await repo.upsert_record("AGE-2", {"issue_key": "AGE-2", "sdl_approval": "requested", "status": "sdl_requested"})

    db = await get_db()
    await db.execute("UPDATE rab_records SET updated_at = '2000-01-01T00:00:00+00:00' WHERE issue_key = 'AGE-2'")
    await db.commit()

    records = await repo.get_aging_records(days=2)
    keys = [r["issue_key"] for r in records]
    assert "AGE-2" in keys
    assert "AGE-1" not in keys
