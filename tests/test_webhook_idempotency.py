"""Tests for webhook idempotency via X-Idempotency-Key header."""

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


class TestWebhookIdempotency:
    def test_without_idempotency_key_still_works(self, client: TestClient) -> None:
        response = client.post(
            "/webhooks/jira",
            json={"webhookEvent": "jira:issue_created", "issue": {"key": "TEST-1"}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["idempotent_replay"] is False

    def test_with_idempotency_key_first_call(self, client: TestClient) -> None:
        response = client.post(
            "/webhooks/jira",
            json={"webhookEvent": "jira:issue_created", "issue": {"key": "TEST-1"}},
            headers={"X-Idempotency-Key": "idem-first"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["idempotent_replay"] is False

    def test_with_idempotency_key_duplicate(self, client: TestClient) -> None:
        client.post(
            "/webhooks/jira",
            json={"webhookEvent": "jira:issue_created", "issue": {"key": "TEST-1"}},
            headers={"X-Idempotency-Key": "idem-dup"},
        )
        response = client.post(
            "/webhooks/jira",
            json={"webhookEvent": "jira:issue_created", "issue": {"key": "TEST-1"}},
            headers={"X-Idempotency-Key": "idem-dup"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["idempotent_replay"] is True

    def test_idempotency_is_per_key(self, client: TestClient) -> None:
        r1 = client.post(
            "/webhooks/jira",
            json={"webhookEvent": "jira:issue_created", "issue": {"key": "TEST-1"}},
            headers={"X-Idempotency-Key": "idem-key-a"},
        )
        r2 = client.post(
            "/webhooks/jira",
            json={"webhookEvent": "jira:issue_created", "issue": {"key": "TEST-1"}},
            headers={"X-Idempotency-Key": "idem-key-b"},
        )
        assert r1.json()["idempotent_replay"] is False
        assert r2.json()["idempotent_replay"] is False

    def test_duplicate_returns_cached_result(self, client: TestClient) -> None:
        client.post(
            "/webhooks/jira",
            json={"webhookEvent": "jira:issue_created", "issue": {"key": "TEST-1"}},
            headers={"X-Idempotency-Key": "idem-result"},
        )
        response = client.post(
            "/webhooks/jira",
            json={"webhookEvent": "jira:issue_created", "issue": {"key": "TEST-1"}},
            headers={"X-Idempotency-Key": "idem-result"},
        )
        data = response.json()
        assert data["idempotent_replay"] is True
        assert data["result"] is not None
