"""Tests for the health and root endpoints."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure required env vars are set for the test app."""
    monkeypatch.setenv("JIRA_WEBHOOK_URL", "http://testserver/webhooks/jira")
    monkeypatch.setenv("APP_ENV", "test")


@pytest.fixture(autouse=True)
def _mock_jira_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock JiraClient.check_connection to avoid real network calls."""

    async def mock_check_connection(self) -> dict:
        return {"connected": True, "details": "Jira API is reachable and authenticated."}

    from app.services.jira_client import JiraClient

    monkeypatch.setattr(JiraClient, "check_connection", mock_check_connection)


@pytest.fixture()
def client() -> TestClient:
    """Create a fresh TestClient for each test."""
    from app.main import create_app

    return TestClient(create_app())


class TestHealthEndpoint:
    """GET /health"""

    def test_returns_200(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200

    def test_response_contains_status_ok(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert data["status"] == "ok"

    def test_response_contains_service_name(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert data["service"] == "rab-automation"

    def test_response_contains_environment(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert data["environment"] == "test"

    def test_response_contains_jira_connection(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert data["jira"]["connected"] is True
        assert "Jira API is reachable and authenticated." in data["jira"]["details"]


class TestRootEndpoint:
    """GET /"""

    def test_returns_200(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200

    def test_response_contains_service_name(self, client: TestClient) -> None:
        data = client.get("/").json()
        assert data["service"] == "rab-automation"

    def test_response_contains_status_running(self, client: TestClient) -> None:
        data = client.get("/").json()
        assert data["status"] == "running"
