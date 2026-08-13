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
        assert response.status_code == 200
        assert response.json() is None

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
