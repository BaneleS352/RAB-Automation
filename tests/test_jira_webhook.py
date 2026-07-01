"""Tests for the POST /webhooks/jira endpoint."""

import pytest
from fastapi.testclient import TestClient

VALID_PAYLOAD = {
    "webhookEvent": "jira:issue_created",
    "issue": {"key": "ABC-123"},
}

TEST_WEBHOOK_URL = "http://testserver/webhooks/jira"


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure required env vars are set for the test app."""
    monkeypatch.setenv("JIRA_WEBHOOK_URL", TEST_WEBHOOK_URL)
    monkeypatch.setenv("APP_ENV", "test")


@pytest.fixture()
def client() -> TestClient:
    """Create a fresh TestClient for each test."""
    from app.main import create_app

    return TestClient(create_app())


class TestJiraWebhookSuccess:
    """Valid webhook requests."""

    def test_returns_200(self, client: TestClient) -> None:
        response = client.post("/webhooks/jira", json=VALID_PAYLOAD)
        assert response.status_code == 200

    def test_response_status_accepted(self, client: TestClient) -> None:
        data = client.post("/webhooks/jira", json=VALID_PAYLOAD).json()
        assert data["status"] == "accepted"

    def test_response_issue_key(self, client: TestClient) -> None:
        data = client.post("/webhooks/jira", json=VALID_PAYLOAD).json()
        assert data["issue_key"] == "ABC-123"

    def test_response_event_type(self, client: TestClient) -> None:
        data = client.post("/webhooks/jira", json=VALID_PAYLOAD).json()
        assert data["event_type"] == "jira:issue_created"

    def test_response_result_queued(self, client: TestClient) -> None:
        data = client.post("/webhooks/jira", json=VALID_PAYLOAD).json()
        assert data["result"] == "queued_for_processing"


class TestJiraWebhookMissingIssueKey:
    """Payloads with an issue object but no key."""

    def test_returns_400(self, client: TestClient) -> None:
        payload = {"webhookEvent": "jira:issue_created", "issue": {}}
        response = client.post("/webhooks/jira", json=payload)
        assert response.status_code == 400

    def test_response_detail(self, client: TestClient) -> None:
        payload = {"webhookEvent": "jira:issue_created", "issue": {}}
        data = client.post("/webhooks/jira", json=payload).json()
        assert data["detail"] == "Missing Jira issue key in webhook payload"


class TestJiraWebhookMissingIssueObject:
    """Payloads without an issue object at all."""

    def test_returns_400(self, client: TestClient) -> None:
        payload = {"webhookEvent": "jira:issue_created"}
        response = client.post("/webhooks/jira", json=payload)
        assert response.status_code == 400

    def test_response_detail(self, client: TestClient) -> None:
        payload = {"webhookEvent": "jira:issue_created"}
        data = client.post("/webhooks/jira", json=payload).json()
        assert data["detail"] == "Missing Jira issue key in webhook payload"
