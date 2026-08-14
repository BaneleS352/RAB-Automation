"""Tests for webhook idempotency via X-Idempotency-Key header."""

import asyncio

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_WEBHOOK_URL", "http://testserver/webhooks/jira")
    monkeypatch.setenv("APP_ENV", "test")


@pytest.fixture(autouse=True)
def _mock_jira(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.jira_client import JiraClient

    async def mock_get_issue(self, issue_key, fields=None):
        return {
            "key": issue_key,
            "fields": {
                "summary": "Test issue",
                "assignee": {"displayName": "Assignee"},
                "reporter": {"displayName": "Reporter"},
            },
        }

    async def mock_add_comment(self, issue_key, body):
        return {}

    monkeypatch.setattr(JiraClient, "get_issue", mock_get_issue)
    monkeypatch.setattr(JiraClient, "add_comment", mock_add_comment)


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

    def test_duplicate_returns_orchestration_result_not_record_status(self, client: TestClient) -> None:
        """Replay must surface the original orchestration result, not the DB record status."""
        client.post(
            "/webhooks/jira",
            json={"webhookEvent": "jira:issue_created", "issue": {"key": "RES-1"}},
            headers={"X-Idempotency-Key": "res-idem"},
        )
        response = client.post(
            "/webhooks/jira",
            json={"webhookEvent": "jira:issue_created", "issue": {"key": "RES-1"}},
            headers={"X-Idempotency-Key": "res-idem"},
        )
        data = response.json()
        assert data["idempotent_replay"] is True
        assert data["result"] == "approval_requested_sdl"

    def test_non_start_event_is_ignored(self, client: TestClient) -> None:
        response = client.post(
            "/webhooks/jira",
            json={"webhookEvent": "jira:comment_created", "issue": {"key": "IGN-1"}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["result"] == "ignored_non_start_event"
        assert data["idempotent_replay"] is False

    def test_restart_event_with_active_flow_is_ignored(self, client: TestClient) -> None:
        client.post(
            "/webhooks/jira",
            json={"webhookEvent": "jira:issue_created", "issue": {"key": "RESTART-1"}},
            headers={"X-Idempotency-Key": "restart-a"},
        )
        response = client.post(
            "/webhooks/jira",
            json={"webhookEvent": "jira:issue_created", "issue": {"key": "RESTART-1"}},
            headers={"X-Idempotency-Key": "restart-b"},
        )
        data = response.json()
        assert data["result"] == "already_in_progress"
        assert data["idempotent_replay"] is False


class TestEventLockEviction:
    @pytest.mark.asyncio
    async def test_locked_oldest_lock_is_not_evicted(self) -> None:
        from app.api import webhooks as webhooks_module

        webhooks_module._event_locks.clear()
        for i in range(webhooks_module._MAX_EVENT_LOCKS):
            webhooks_module._event_locks[f"lock-{i}"] = asyncio.Lock()

        await webhooks_module._event_locks["lock-0"].acquire()
        try:
            new_lock = webhooks_module._get_event_lock("lock-new")
        finally:
            webhooks_module._event_locks["lock-0"].release()

        assert webhooks_module._event_locks.get("lock-new") is new_lock
        assert "lock-0" in webhooks_module._event_locks
        assert len(webhooks_module._event_locks) <= webhooks_module._MAX_EVENT_LOCKS

    @pytest.mark.asyncio
    async def test_unlocked_oldest_is_evicted_when_full(self) -> None:
        from app.api import webhooks as webhooks_module

        webhooks_module._event_locks.clear()
        for i in range(webhooks_module._MAX_EVENT_LOCKS):
            webhooks_module._event_locks[f"lock-{i}"] = asyncio.Lock()

        new_lock = webhooks_module._get_event_lock("lock-new-2")
        assert "lock-0" not in webhooks_module._event_locks
        assert webhooks_module._event_locks.get("lock-new-2") is new_lock
        assert len(webhooks_module._event_locks) == webhooks_module._MAX_EVENT_LOCKS


class TestWebhookLedger:
    @pytest.mark.asyncio
    async def test_unkeyed_webhook_is_still_logged(self, client: TestClient) -> None:
        from app.repositories.rab_repository import RabRepository

        client.post(
            "/webhooks/jira",
            json={"webhookEvent": "jira:issue_created", "issue": {"key": "LOG-1"}},
        )
        events = await RabRepository().get_webhook_events(limit=50)
        assert any(e["issue_key"] == "LOG-1" for e in events)

    @pytest.mark.asyncio
    async def test_webhook_status_updated_after_processing(self, client: TestClient) -> None:
        from app.repositories.rab_repository import RabRepository

        client.post(
            "/webhooks/jira",
            json={"webhookEvent": "jira:issue_created", "issue": {"key": "LOG-2"}},
            headers={"X-Idempotency-Key": "ledger-1"},
        )
        events = await RabRepository().get_webhook_events(limit=50)
        match = [e for e in events if e["event_id"] == "ledger-1"]
        assert match
        assert match[0]["status"] == "approval_requested_sdl"
