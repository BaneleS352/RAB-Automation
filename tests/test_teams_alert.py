"""Tests for the Teams release_ready alert integration.

This is the one customer-facing integration with zero coverage elsewhere: a
regression here pages real people, so the contract is pinned down explicitly —
no-POST when unconfigured, correct AdaptiveCard shape when configured, and
bounded retry on transient failures.
"""

import pytest

from app.services import teams_alert
from app.services.teams_alert import _build_release_card, send_release_ready_alert


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_WEBHOOK_URL", "http://testserver/webhooks/jira")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("APP_PUBLIC_URL", "https://rab.example.com")


class _FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "", headers: dict | None = None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


class _FakeClient:
    """Stand-in for httpx.AsyncClient recording POSTs and replaying responses."""

    def __init__(self, calls: list, responses: list, *args, **kwargs) -> None:
        self._calls = calls
        self._responses = responses

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, url, json=None, headers=None):
        self._calls.append({"url": url, "json": json, "headers": headers})
        assert self._responses, "unexpected extra POST in test"
        return self._responses.pop(0)


def _patch_client(monkeypatch: pytest.MonkeyPatch, responses: list) -> list:
    calls: list = []
    monkeypatch.setattr(
        teams_alert.httpx,
        "AsyncClient",
        lambda *args, **kwargs: _FakeClient(calls, responses, *args, **kwargs),
    )
    return calls


class TestSendReleaseReadyAlert:
    @pytest.mark.asyncio
    async def test_no_post_when_unconfigured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEAMS_WORKFLOW_WEBHOOK_URL", "")
        monkeypatch.setenv("TEAMS_WEBHOOK_URL", "")
        calls = _patch_client(monkeypatch, [_FakeResponse(200)])
        assert await send_release_ready_alert("TEST-1", "Summary") is False
        assert calls == []

    @pytest.mark.asyncio
    async def test_posts_card_to_configured_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEAMS_WORKFLOW_WEBHOOK_URL", "https://prod.example.com/workflows/abc")
        calls = _patch_client(monkeypatch, [_FakeResponse(202)])
        assert await send_release_ready_alert("TEST-9", "Release summary", {"priority": "High"}) is True
        assert len(calls) == 1
        assert calls[0]["url"] == "https://prod.example.com/workflows/abc"
        assert calls[0]["headers"] == {"Content-Type": "application/json"}
        card = calls[0]["json"]
        assert card["type"] == "AdaptiveCard"
        assert "adaptivecards.io" in card["$schema"]
        urls = [a["url"] for a in card["actions"]]
        assert "https://example.atlassian.net/browse/TEST-9" in urls
        assert "https://rab.example.com/dashboard/records/TEST-9" in urls

    @pytest.mark.asyncio
    async def test_no_placeholder_hosts_when_bases_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEAMS_WORKFLOW_WEBHOOK_URL", "https://prod.example.com/workflows/abc")
        monkeypatch.setenv("JIRA_BASE_URL", "")
        monkeypatch.setenv("APP_PUBLIC_URL", "")
        # Custom webhook path: no dashboard URL can be derived from it either.
        monkeypatch.setenv("JIRA_WEBHOOK_URL", "https://hooks.example.com/custom-path")
        calls = _patch_client(monkeypatch, [_FakeResponse(200)])
        assert await send_release_ready_alert("TEST-1", "Summary") is True
        card = calls[0]["json"]
        assert card["actions"] == []
        assert "yourcompany" not in str(card)

    @pytest.mark.asyncio
    async def test_retries_transient_then_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEAMS_WORKFLOW_WEBHOOK_URL", "https://prod.example.com/workflows/abc")
        calls = _patch_client(
            monkeypatch,
            [_FakeResponse(500, "boom", {"Retry-After": "0"}), _FakeResponse(200)],
        )
        assert await send_release_ready_alert("TEST-1", "Summary") is True
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_gives_up_after_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEAMS_WORKFLOW_WEBHOOK_URL", "https://prod.example.com/workflows/abc")
        calls = _patch_client(
            monkeypatch,
            [_FakeResponse(500, "boom", {"Retry-After": "0"})] * 3,
        )
        assert await send_release_ready_alert("TEST-1", "Summary") is False
        assert len(calls) == 3

    @pytest.mark.asyncio
    async def test_client_error_does_not_retry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEAMS_WORKFLOW_WEBHOOK_URL", "https://prod.example.com/workflows/abc")
        calls = _patch_client(monkeypatch, [_FakeResponse(400, "bad request")])
        assert await send_release_ready_alert("TEST-1", "Summary") is False
        assert len(calls) == 1


class TestBuildReleaseCard:
    def test_truncates_long_values(self) -> None:
        card = _build_release_card("TEST-1", "S", {"priority": "P" * 200, "validation_result": "V" * 500})
        facts = {f["title"]: f["value"] for f in card["body"][2]["facts"]}
        assert facts["Priority"] == "P" * 120
        assert facts["RAB audit"] == "V" * 180

    def test_blank_summary_falls_back(self) -> None:
        card = _build_release_card("TEST-1", "", {})
        assert card["body"][1]["text"] == "No summary"
