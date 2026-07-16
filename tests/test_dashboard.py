"""Tests for the HTML dashboard views."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_WEBHOOK_URL", "http://testserver/webhooks/jira")
    monkeypatch.setenv("APP_ENV", "test")


@pytest.fixture(autouse=True)
def _mock_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.jira_client import JiraClient
    from app.services.azure_devops_client import AzureDevOpsClient
    from app.services.teams_client import TeamsClient

    async def mock_check(self):
        return True
    monkeypatch.setattr(JiraClient, "check_connection", mock_check)
    monkeypatch.setattr(AzureDevOpsClient, "check_connection", mock_check)
    monkeypatch.setattr(TeamsClient, "check_connection", mock_check)


@pytest.fixture()
def client() -> TestClient:
    from app.main import create_app
    return TestClient(create_app())


class TestDashboardHealth:
    def test_returns_html(self, client: TestClient) -> None:
        response = client.get("/dashboard/health")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")

    def test_contains_health_cards(self, client: TestClient) -> None:
        body = client.get("/dashboard/health").text
        assert "health-card" in body
        assert "jira" in body.lower()
        assert "azure_devops" in body.lower() or "azure" in body.lower()
        assert "teams" in body.lower()

    def test_shows_connected_status(self, client: TestClient) -> None:
        body = client.get("/dashboard/health").text
        assert "Connected" in body

    def test_contains_navigation(self, client: TestClient) -> None:
        body = client.get("/dashboard/health").text
        assert "nav" in body
        assert "Audit Records" in body


class TestDashboardRecords:
    def test_returns_html(self, client: TestClient) -> None:
        response = client.get("/dashboard/records")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")

    def test_shows_title(self, client: TestClient) -> None:
        body = client.get("/dashboard/records").text
        assert "RAB Audit Records" in body

    def test_shows_empty_state(self, client: TestClient) -> None:
        body = client.get("/dashboard/records").text
        assert "No audit records found" in body


class TestRootRedirect:
    def test_root_returns_health_content(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert "health-card" in response.text or "RAB Automation" in response.text
