"""Tests for the health and root endpoints."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_WEBHOOK_URL", "http://testserver/webhooks/jira")
    monkeypatch.setenv("APP_ENV", "test")


@pytest.fixture(autouse=True)
def _mock_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.jira_client import JiraClient

    async def mock_jira_check(self):
        return {"connected": True, "details": "Jira API is reachable and authenticated."}
    monkeypatch.setattr(JiraClient, "check_connection", mock_jira_check)

    from app.services.azure_devops_client import AzureDevOpsClient

    async def mock_azure_check(self):
        return {"connected": True, "details": "Azure DevOps API is reachable and authenticated."}
    monkeypatch.setattr(AzureDevOpsClient, "check_connection", mock_azure_check)

    from app.services.teams_client import TeamsClient

    async def mock_teams_check(self):
        return {"connected": True, "details": "Azure Bot authentication succeeded."}
    monkeypatch.setattr(TeamsClient, "check_connection", mock_teams_check)


@pytest.fixture()
def client() -> TestClient:
    from app.main import create_app
    return TestClient(create_app())


class TestHealthEndpoint:
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

    def test_contains_jira_connection(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert data["jira"]["connected"] is True

    def test_contains_azure_devops_connection(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert data["azure_devops"]["connected"] is True

    def test_contains_teams_connection(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert data["teams"]["connected"] is True


class TestRootEndpoint:
    def test_root_redirects_to_dashboard(self, client: TestClient) -> None:
        response = client.get("/", follow_redirects=False)
        assert response.status_code in (302, 307)

    def test_root_followed_returns_html(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert "health-card" in response.text
