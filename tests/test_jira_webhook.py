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


@pytest.fixture(autouse=True)
def mock_jira_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock JiraClient methods to avoid real network calls."""
    from app.services.jira_client import JiraClient

    async def mock_get_issue(self, issue_key: str, fields: str | None = None):
        return {
            "id": "10000",
            "key": issue_key,
            "fields": {
                "summary": "Test issue",
                "assignee": {"displayName": "Test User"},
                "reporter": {"displayName": "Reporter User"},
            },
        }

    async def mock_add_comment(self, issue_key: str, body: str) -> dict:
        return {"id": "10001"}

    monkeypatch.setattr(JiraClient, "get_issue", mock_get_issue)
    monkeypatch.setattr(JiraClient, "add_comment", mock_add_comment)
    monkeypatch.setattr(JiraClient, "get_issue_comments", lambda self, k: [])
    monkeypatch.setattr(JiraClient, "update_issue", lambda self, k, f: {})
    monkeypatch.setattr(JiraClient, "transition_issue", lambda self, k, t: {})


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

    def test_response_result_approval_requested(self, client: TestClient) -> None:
        data = client.post("/webhooks/jira", json=VALID_PAYLOAD).json()
        assert data["result"] == "approval_requested_sdl"


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
