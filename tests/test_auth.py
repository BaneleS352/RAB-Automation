"""Tests for the optional ACCESS_TOKEN middleware."""

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


class TestAccessTokenOpenByDefault:
    def test_requests_allowed_without_token(self, client: TestClient) -> None:
        assert client.get("/health").status_code == 200


class TestAccessTokenEnforced:
    @pytest.fixture(autouse=True)
    def _set_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ACCESS_TOKEN", "secret-token")

    def test_missing_token_rejected(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 401

    def test_bearer_token_accepted(self, client: TestClient) -> None:
        response = client.get("/health", headers={"Authorization": "Bearer secret-token"})
        assert response.status_code == 200

    def test_x_api_key_accepted(self, client: TestClient) -> None:
        response = client.get("/health", headers={"X-API-Key": "secret-token"})
        assert response.status_code == 200

    def test_wrong_token_rejected(self, client: TestClient) -> None:
        response = client.get("/health", headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401

    def test_query_param_accepted_and_sets_cookie(self, client: TestClient) -> None:
        response = client.get("/dashboard/health", params={"access_token": "secret-token"})
        assert response.status_code == 200
        assert "rab_access_token" in response.headers.get("set-cookie", "")

    def test_cookie_accepted(self, client: TestClient) -> None:
        client.cookies.set("rab_access_token", "secret-token")
        response = client.get("/health")
        assert response.status_code == 200

    def test_static_assets_bypass_auth(self, client: TestClient) -> None:
        response = client.get("/static/style.css")
        assert response.status_code != 401

    def test_mutating_webhook_protected(self, client: TestClient) -> None:
        response = client.post(
            "/webhooks/jira",
            json={"webhookEvent": "jira:issue_created", "issue": {"key": "AUTH-1"}},
        )
        assert response.status_code == 401
