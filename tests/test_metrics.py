"""Tests for the /metrics endpoint."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_WEBHOOK_URL", "http://testserver/webhooks/jira")
    monkeypatch.setenv("APP_ENV", "test")


@pytest.fixture()
def client() -> TestClient:
    from app.main import create_app
    return TestClient(create_app())


class TestMetricsEndpoint:
    def test_returns_200(self, client: TestClient) -> None:
        response = client.get("/metrics")
        assert response.status_code == 200

    def test_contains_required_fields(self, client: TestClient) -> None:
        data = client.get("/metrics").json()
        assert "uptime_seconds" in data
        assert "requests_total" in data
        assert "requests_failed" in data
        assert "avg_duration_ms" in data
        assert "queue_pending" in data
        assert "queue_tasks_completed" in data
        assert "queue_tasks_failed" in data

    def test_uptime_is_positive(self, client: TestClient) -> None:
        data = client.get("/metrics").json()
        assert data["uptime_seconds"] > 0

    def test_requests_total_increments(self, client: TestClient) -> None:
        data1 = client.get("/metrics").json()
        data2 = client.get("/metrics").json()
        assert data2["requests_total"] >= data1["requests_total"]

    def test_queue_defaults(self, client: TestClient) -> None:
        data = client.get("/metrics").json()
        assert data["queue_pending"] >= 0
        assert data["queue_tasks_completed"] >= 0
        assert data["queue_tasks_failed"] >= 0

    def test_avg_duration_is_float(self, client: TestClient) -> None:
        data = client.get("/metrics").json()
        assert isinstance(data["avg_duration_ms"], float)
