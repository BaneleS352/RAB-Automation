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
async def test_get_all_records_pagination(repo: RabRepository) -> None:
    for i in range(5):
        await repo.record_validation(f"PAGE-{i}", True, f"Record {i}")
    all_records = await repo.get_all_records(limit=3, offset=0)
    assert len(all_records) <= 3


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
