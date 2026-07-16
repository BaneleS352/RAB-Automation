"""Tests for JiraClient."""

import pytest
from app.services.jira_client import JiraClient, JiraClientError


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_WEBHOOK_URL", "http://testserver/webhooks/jira")
    monkeypatch.setenv("JIRA_BASE_URL", "https://test.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "test@test.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "test-token")


class TestJiraClient:
    @pytest.mark.asyncio
    async def test_raises_when_unconfigured(self, monkeypatch):
        monkeypatch.setenv("JIRA_BASE_URL", "")
        client = JiraClient()
        with pytest.raises(JiraClientError, match="configuration is incomplete"):
            await client._get("/rest/api/3/myself")

    @pytest.mark.asyncio
    async def test_check_connection_returns_false_on_failure(self, monkeypatch):
        monkeypatch.setenv("JIRA_BASE_URL", "")
        client = JiraClient()
        result = await client.check_connection()
        assert result["connected"] is False

    @pytest.mark.asyncio
    async def test_get_issue_comments_empty(self, monkeypatch):
        async def mock_get(self, path, params=None):
            return {"comments": []}
        monkeypatch.setattr(JiraClient, "_get", mock_get)
        client = JiraClient()
        comments = await client.get_issue_comments("TEST-1")
        assert comments == []

    @pytest.mark.asyncio
    async def test_add_comment(self, monkeypatch):
        async def mock_post(self, path, body):
            return {"id": "12345"}
        monkeypatch.setattr(JiraClient, "_post", mock_post)
        client = JiraClient()
        result = await client.add_comment("TEST-1", "test comment")
        assert result["id"] == "12345"

    @pytest.mark.asyncio
    async def test_update_issue(self, monkeypatch):
        async def mock_put(self, path, body):
            return {}
        monkeypatch.setattr(JiraClient, "_put", mock_put)
        client = JiraClient()
        result = await client.update_issue("TEST-1", {"summary": "new"})
        assert result == {}

    @pytest.mark.asyncio
    async def test_transition_issue(self, monkeypatch):
        async def mock_post(self, path, body):
            return {}
        monkeypatch.setattr(JiraClient, "_post", mock_post)
        client = JiraClient()
        result = await client.transition_issue("TEST-1", "11")
        assert result == {}
