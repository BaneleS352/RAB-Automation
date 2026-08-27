"""Tests for the health and root endpoints - updated for integration removal."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_WEBHOOK_URL", "http://testserver/webhooks/jira")
    monkeypatch.setenv("APP_ENV", "test")


@pytest.fixture(autouse=True)
def _mock_jira_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.health import _health_cache
    from app.services.jira_client import JiraClient

    _health_cache["services"] = None
    _health_cache["at"] = 0.0

    async def mock_jira_check(self):
        return {"connected": True, "details": "Jira API is reachable and authenticated."}
    monkeypatch.setattr(JiraClient, "check_connection", mock_jira_check)


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

    def test_jira_is_only_service_reported(self, client: TestClient) -> None:
        data = client.get("/health").json()
        # Only jira should be reported; azure_devops and teams are removed
        assert "jira" in data
        assert data["jira"]["connected"] is True
        assert data["service"] == "rab-automation"
        assert data["environment"] == "test"
    def test_connection_checks_are_cached_within_ttl(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.api.health import _health_cache
        from app.services.jira_client import JiraClient

        _health_cache["services"] = None
        _health_cache["at"] = 0.0
        calls = {"jira": 0}

        async def jira_check(self):
            calls["jira"] += 1
            return {"connected": True, "details": "ok"}

        monkeypatch.setattr(JiraClient, "check_connection", jira_check)

        client.get("/health")
        client.get("/health")
        assert calls["jira"] == 1


class TestRootEndpoint:
    def test_root_redirects_to_dashboard(self, client: TestClient) -> None:
        response = client.get("/", follow_redirects=False)
        assert response.status_code in (302, 307)

    def test_root_followed_returns_html(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert "health-card" in response.text