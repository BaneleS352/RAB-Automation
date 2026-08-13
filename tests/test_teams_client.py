"""Tests for TeamsClient and card templates."""

import json

import httpx
import pytest
from app.services.card_templates import (
    approval_request_card,
    developer_notification_card,
    meeting_decision_card,
    rejection_notification_card,
    to_message_card,
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


class TestToMessageCard:
    def test_converts_submit_to_httppost(self):
        card = approval_request_card("TEST-1", "Release v1", "SDL", "approval-1")
        message = to_message_card(card, callback_url="https://example.com/webhooks/teams")
        assert message["@type"] == "MessageCard"
        assert message["title"] == "RAB Approval Request: TEST-1"
        assert "Release v1" in message["text"]
        actions = message["potentialAction"]
        assert len(actions) == 2
        for action in actions:
            assert action["@type"] == "HttpPOST"
            assert action["target"] == "https://example.com/webhooks/teams"
            data = json.loads(action["body"])
            assert data["issue_key"] == "TEST-1"
        assert actions[0]["name"] == "Approve"
        assert json.loads(actions[0]["body"])["action"] == "approve"
        assert json.loads(actions[1]["body"])["action"] == "reject"

    def test_drops_actions_without_callback_url(self):
        card = approval_request_card("TEST-1", "Release", "SDL", "approval-1")
        message = to_message_card(card, callback_url="")
        assert "potentialAction" not in message

    def test_preserves_facts(self):
        card = developer_notification_card("TEST-1", ["PR Link", "QA"])
        message = to_message_card(card, callback_url="https://example.com")
        assert "**PR Link:** Missing" in message["text"]
        assert "**QA:** Missing" in message["text"]

    def test_opens_url_action_becomes_openuri(self):
        card = {
            "type": "AdaptiveCard",
            "body": [{"type": "TextBlock", "text": "Open Jira"}],
            "actions": [
                {"type": "Action.OpenUrl", "title": "View ticket", "url": "https://jira/XYZ-1"}
            ],
        }
        message = to_message_card(card, callback_url="https://example.com")
        action = message["potentialAction"][0]
        assert action["@type"] == "OpenUri"
        assert action["targets"][0]["uri"] == "https://jira/XYZ-1"

    def test_text_only_card_has_summary_fallback(self):
        message = to_message_card(
            {"type": "AdaptiveCard", "body": [{"type": "TextBlock", "text": "Release ready: XYZ-1"}]}
        )
        assert message["title"] == ""
        assert message["summary"] == "Release ready: XYZ-1"


class FakeTeamsResponse:
    status_code = 200
    text = "1"

    def raise_for_status(self) -> None:
        return None


class FakeTeamsHttpClient:
    def __init__(self, *args, **kwargs) -> None:
        self.sent: dict = {}

    async def __aenter__(self) -> "FakeTeamsHttpClient":
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    async def post(self, url: str, json: dict | None = None, headers: dict | None = None):
        self.sent = {"url": url, "json": json, "headers": headers}
        return FakeTeamsResponse()


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_WEBHOOK_URL", "http://testserver/webhooks/jira")


class TestTeamsClient:
    @pytest.mark.asyncio
    async def test_check_connection_not_configured(self, monkeypatch):
        monkeypatch.setenv("TEAMS_BOT_APP_ID", "")
        monkeypatch.setenv("TEAMS_BOT_CLIENT_SECRET", "")
        monkeypatch.setenv("TEAMS_WEBHOOK_URL", "")
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

    def test_is_configured_via_webhook(self, monkeypatch):
        monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://outlook.office.com/webhook/abc")
        client = TeamsClient()
        assert client._is_configured() is True
        assert client._is_webhook_configured() is True

    @pytest.mark.asyncio
    async def test_check_connection_webhook_mode(self, monkeypatch):
        monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://outlook.office.com/webhook/abc")
        client = TeamsClient()
        result = await client.check_connection()
        assert result["connected"] is True
        assert "webhook" in result["details"]

    @pytest.mark.asyncio
    async def test_send_adaptive_card_via_webhook(self, monkeypatch):
        monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://outlook.office.com/webhook/abc")
        monkeypatch.setenv("TEAMS_CALLBACK_URL", "https://example.com/webhooks/teams")
        fake = FakeTeamsHttpClient()
        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: fake)
        client = TeamsClient()
        card = approval_request_card("TEST-1", "Release v1", "SDL", "approval-1")
        result = await client.send_adaptive_card_via_webhook(card)
        assert result["status"] == 200
        assert fake.sent["url"] == "https://outlook.office.com/webhook/abc"
        sent = fake.sent["json"]
        assert sent["@type"] == "MessageCard"
        assert sent["potentialAction"][0]["@type"] == "HttpPOST"
        assert sent["potentialAction"][0]["target"] == "https://example.com/webhooks/teams"

    @pytest.mark.asyncio
    async def test_send_message_via_webhook(self, monkeypatch):
        monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://outlook.office.com/webhook/abc")
        fake = FakeTeamsHttpClient()
        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: fake)
        client = TeamsClient()
        await client.send_message_via_webhook("Release ready: XYZ-1")
        assert fake.sent["json"]["text"] == "Release ready: XYZ-1"

    @pytest.mark.asyncio
    async def test_send_adaptive_card_via_webhook_raises_when_unconfigured(self, monkeypatch):
        monkeypatch.setenv("TEAMS_WEBHOOK_URL", "")
        client = TeamsClient()
        with pytest.raises(Exception, match="TEAMS_WEBHOOK_URL"):
            await client.send_adaptive_card_via_webhook({"type": "AdaptiveCard"})


class TestOrchestratorWebhookDelivery:
    @pytest.mark.asyncio
    async def test_send_card_prefers_webhook(self, monkeypatch):
        monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://outlook.office.com/webhook/abc")
        from app.services.rab_orchestrator import RabOrchestrator

        calls = []

        async def fake_send(card):
            calls.append(card)

        client = TeamsClient()
        monkeypatch.setattr(client, "send_adaptive_card_via_webhook", fake_send)
        orch = RabOrchestrator(teams_client=client)
        await orch._send_card("Title", {"type": "AdaptiveCard", "body": []})
        assert calls == [{"type": "AdaptiveCard", "body": []}]

    @pytest.mark.asyncio
    async def test_send_card_skips_when_unconfigured(self, monkeypatch):
        monkeypatch.setenv("TEAMS_WEBHOOK_URL", "")
        monkeypatch.setenv("TEAMS_BOT_APP_ID", "")
        monkeypatch.setenv("TEAMS_BOT_CLIENT_SECRET", "")
        from app.services.rab_orchestrator import RabOrchestrator

        calls = []

        async def fake_send(card):
            calls.append(card)

        client = TeamsClient()
        monkeypatch.setattr(client, "send_adaptive_card_via_webhook", fake_send)
        orch = RabOrchestrator(teams_client=client)
        await orch._send_card("Title", {"type": "AdaptiveCard", "body": []})
        assert calls == []
