"""Tests for the Teams Bot Framework webhook endpoint."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_WEBHOOK_URL", "http://testserver/webhooks/jira")


@pytest.fixture(autouse=True)
def _mock_orchestrator(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.rab_orchestrator import RabOrchestrator

    async def mock_callback(self, issue_key, action, approver="", reason=None):
        return {"status": "approved", "detail": "done"}

    async def mock_meeting(self, issue_key, needs_meeting):
        return "ok"

    monkeypatch.setattr(RabOrchestrator, "handle_approval_callback", mock_callback)
    monkeypatch.setattr(RabOrchestrator, "handle_meeting_callback", mock_meeting)


@pytest.fixture()
def client() -> TestClient:
    from app.main import create_app
    return TestClient(create_app())


class TestTeamsWebhook:
    def test_conversation_update(self, client: TestClient) -> None:
        payload = {
            "type": "conversationUpdate",
            "membersAdded": [{"id": "user-123", "name": "Test User"}],
            "recipient": {"id": "bot-456"},
            "conversation": {"id": "conv-1", "tenantId": "tenant-1"},
            "serviceUrl": "https://smba.trafficmanager.net/amer/",
        }
        response = client.post("/webhooks/teams", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_approve_action(self, client: TestClient) -> None:
        payload = {
            "type": "message",
            "value": {"action": "approve", "approval_id": "abc", "issue_key": "TEST-1"},
            "from": {"name": "SDL User"},
        }
        response = client.post("/webhooks/teams", json=payload)
        assert response.status_code == 200

    def test_reject_action(self, client: TestClient) -> None:
        payload = {
            "type": "message",
            "value": {"action": "reject", "approval_id": "xyz", "issue_key": "TEST-1"},
            "from": {"name": "SDM User"},
        }
        response = client.post("/webhooks/teams", json=payload)
        assert response.status_code == 200

    def test_meeting_yes(self, client: TestClient) -> None:
        payload = {
            "type": "message",
            "value": {"action": "meeting_yes", "issue_key": "TEST-1"},
        }
        response = client.post("/webhooks/teams", json=payload)
        assert response.status_code == 200

    def test_meeting_no(self, client: TestClient) -> None:
        payload = {
            "type": "message",
            "value": {"action": "meeting_no", "issue_key": "TEST-1"},
        }
        response = client.post("/webhooks/teams", json=payload)
        assert response.status_code == 200
