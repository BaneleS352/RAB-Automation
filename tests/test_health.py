"""Tests for the health and root endpoints."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_WEBHOOK_URL", "http://testserver/webhooks/jira")
    monkeypatch.setenv("APP_ENV", "test")


@pytest.fixture(autouse=True)
def _mock_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.health import _health_cache
    from app.services.jira_client import JiraClient

    _health_cache["services"] = None
    _health_cache["at"] = 0.0

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


class TestHealthCache:
    def test_connection_checks_are_cached_within_ttl(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.api.health import _health_cache
        from app.services.jira_client import JiraClient
        from app.services.azure_devops_client import AzureDevOpsClient
        from app.services.teams_client import TeamsClient

        _health_cache["services"] = None
        _health_cache["at"] = 0.0
        calls = {"jira": 0, "azure": 0, "teams": 0}

        async def jira_check(self):
            calls["jira"] += 1
            return {"connected": True, "details": "ok"}

        async def azure_check(self):
            calls["azure"] += 1
            return {"connected": True, "details": "ok"}

        async def teams_check(self):
            calls["teams"] += 1
            return {"connected": True, "details": "ok"}

        monkeypatch.setattr(JiraClient, "check_connection", jira_check)
        monkeypatch.setattr(AzureDevOpsClient, "check_connection", azure_check)
        monkeypatch.setattr(TeamsClient, "check_connection", teams_check)

        client.get("/health")
        client.get("/health")
        assert calls["jira"] == 1
        assert calls["azure"] == 1
        assert calls["teams"] == 1


class TestRootEndpoint:
    def test_root_redirects_to_dashboard(self, client: TestClient) -> None:
        response = client.get("/", follow_redirects=False)
        assert response.status_code in (302, 307)

    def test_root_followed_returns_html(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert "health-card" in response.text
