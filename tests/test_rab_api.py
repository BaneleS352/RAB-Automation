"""Tests for the /rab/records JSON API endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.repositories.rab_repository import RabRepository


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_WEBHOOK_URL", "http://testserver/webhooks/jira")
    monkeypatch.setenv("APP_ENV", "test")


@pytest.fixture()
def client() -> TestClient:
    from app.main import create_app
    return TestClient(create_app())


class TestRabApi:
    def test_list_records_empty(self, client: TestClient) -> None:
        response = client.get("/rab/records")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 0
        assert "records" in data

    @pytest.mark.asyncio
    async def test_list_records_with_data(self, client: TestClient) -> None:
        repo = RabRepository()
        await repo.record_validation("API-1", True, "OK")
        response = client.get("/rab/records")
        data = response.json()
        keys = [r["issue_key"] for r in data["records"]]
        assert "API-1" in keys

    @pytest.mark.asyncio
    async def test_get_single_record(self, client: TestClient) -> None:
        repo = RabRepository()
        await repo.record_validation("API-2", True, "Valid")
        response = client.get("/rab/records/API-2")
        assert response.status_code == 200
        data = response.json()
        assert data["issue_key"] == "API-2"
        assert data["status"] == "validated"

    def test_get_nonexistent_record(self, client: TestClient) -> None:
        response = client.get("/rab/records/DOES-NOT-EXIST")
        assert response.status_code == 404
        assert response.json()["detail"] == "Issue DOES-NOT-EXIST not found"

    def test_list_records_pagination_params(self, client: TestClient) -> None:
        response = client.get("/rab/records?limit=5&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert len(data["records"]) <= 5

    @pytest.mark.asyncio
    async def test_record_includes_all_fields(self, client: TestClient) -> None:
        repo = RabRepository()
        await repo.upsert_record("API-3", {
            "issue_key": "API-3",
            "summary": "Test ticket",
            "status": "meeting_scheduled",
            "sdl_approval": "approved",
            "sdm_approval": "approved",
            "meeting_needed": 1,
        })
        response = client.get("/rab/records/API-3")
        data = response.json()
        assert data["summary"] == "Test ticket"
        assert data["sdl_approval"] == "approved"
        assert data["sdm_approval"] == "approved"
        assert data["meeting_needed"] == 1

    @pytest.mark.asyncio
    async def test_list_records_filter_by_status(self, client: TestClient) -> None:
        repo = RabRepository()
        await repo.record_validation("FLT-A", True, "OK")
        await repo.upsert_record("FLT-B", {"issue_key": "FLT-B", "status": "release_ready"})
        data = client.get("/rab/records?status=release_ready").json()
        keys = [r["issue_key"] for r in data["records"]]
        assert "FLT-B" in keys
        assert "FLT-A" not in keys

    @pytest.mark.asyncio
    async def test_list_records_search_by_q(self, client: TestClient) -> None:
        repo = RabRepository()
        await repo.upsert_record("SRCH-42", {"issue_key": "SRCH-42"})
        data = client.get("/rab/records?q=SRCH-42").json()
        assert any(r["issue_key"] == "SRCH-42" for r in data["records"])

    @pytest.mark.asyncio
    async def test_webhook_events_endpoint(self, client: TestClient) -> None:
        repo = RabRepository()
        await repo.record_webhook_event("wh-123", "WH-1", "jira:issue_created")
        data = client.get("/rab/webhook-events").json()
        assert data["total"] >= 1
        ids = [e["event_id"] for e in data["events"]]
        assert "wh-123" in ids

    @pytest.mark.asyncio
    async def test_record_events_endpoint(self, client: TestClient) -> None:
        repo = RabRepository()
        await repo.record_approval_event("EVT-K", "SDL", "approve", "Jane", "ok")
        data = client.get("/rab/records/EVT-K/events").json()
        assert data[0]["step"] == "SDL"
        assert data[0]["action"] == "approve"
        assert data[0]["approver"] == "Jane"

    @pytest.mark.asyncio
    async def test_summary_endpoint(self, client: TestClient) -> None:
        repo = RabRepository()
        await repo.record_validation("SUM-A", True, "OK")
        await repo.upsert_record("SUM-B", {
            "issue_key": "SUM-B", "status": "sdl_requested", "sdl_approval": "requested",
        })
        data = client.get("/rab/summary").json()
        assert data["total"] >= 2
        assert "counts" in data
        assert data["pending_approval"] >= 1
