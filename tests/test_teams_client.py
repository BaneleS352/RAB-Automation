"""Tests for TeamsClient and card templates."""

import pytest
from app.services.card_templates import (
    approval_request_card,
    developer_notification_card,
    meeting_decision_card,
    rejection_notification_card,
    validation_failed_card,
    validation_passed_card,
)
from app.services.teams_client import TeamsClient, ConversationReference


class TestCardTemplates:
    def test_validation_failed_card(self):
        card = validation_failed_card("TEST-1", ["Assignee", "PR Link"])
        assert card["type"] == "AdaptiveCard"
        facts = [b for b in card["body"] if b.get("type") == "FactSet"]
        assert len(facts) == 1
        fact_titles = [f["title"] for f in facts[0]["facts"]]
        assert "Assignee" in fact_titles
        assert "PR Link" in fact_titles

    def test_validation_passed_card(self):
        card = validation_passed_card("TEST-1")
        assert "TEST-1" in card["body"][0]["text"]

    def test_approval_request_card(self):
        card = approval_request_card("TEST-1", "Test summary", "SDL", "approval-123")
        assert len(card["actions"]) == 2
        assert card["actions"][0]["title"] == "Approve"
        assert card["actions"][1]["title"] == "Reject"
        assert card["actions"][0]["data"]["approval_id"] == "approval-123"
        assert card["actions"][0]["data"]["action"] == "approve"
        assert card["actions"][0]["data"]["issue_key"] == "TEST-1"

    def test_rejection_notification_card(self):
        card = rejection_notification_card("TEST-1", "SDL", "Missing data")
        body_text = "".join(b.get("text", "") for b in card["body"])
        assert "SDL" in body_text
        assert "Missing data" in body_text

    def test_meeting_decision_card(self):
        card = meeting_decision_card("TEST-1")
        assert len(card["actions"]) == 2
        assert card["actions"][0]["data"]["action"] == "meeting_yes"

    def test_developer_notification_card(self):
        card = developer_notification_card("TEST-1", ["PR Link"])
        body_text = "".join(b.get("text", "") for b in card["body"])
        assert "TEST-1" in body_text
        facts = [b for b in card["body"] if b.get("type") == "FactSet"]
        assert len(facts) == 1
        fact_titles = [f["title"] for f in facts[0]["facts"]]
        assert "PR Link" in fact_titles


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_WEBHOOK_URL", "http://testserver/webhooks/jira")


class TestTeamsClient:
    @pytest.mark.asyncio
    async def test_check_connection_not_configured(self, monkeypatch):
        monkeypatch.setenv("TEAMS_BOT_APP_ID", "")
        monkeypatch.setenv("TEAMS_BOT_CLIENT_SECRET", "")
        client = TeamsClient()
        result = await client.check_connection()
        assert result["connected"] is False
        assert "not configured" in result["details"]

    def test_register_and_get_conversation(self):
        from app.services.teams_client import register_conversation, get_conversation

        ref = ConversationReference(
            conversation_id="conv-1",
            service_url="https://smba.trafficmanager.net/amer/",
            user_id="user-1",
        )
        register_conversation("user-1", ref)
        retrieved = get_conversation("user-1")
        assert retrieved is not None
        assert retrieved.conversation_id == "conv-1"

    def test_is_configured(self, monkeypatch):
        monkeypatch.setenv("TEAMS_BOT_APP_ID", "app-id")
        monkeypatch.setenv("TEAMS_BOT_CLIENT_SECRET", "secret")
        client = TeamsClient()
        assert client._is_configured() is True
