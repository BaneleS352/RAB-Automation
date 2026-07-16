"""Tests for AzureDevOpsClient."""

import pytest
from app.services.azure_devops_client import AzureDevOpsClient, AzureDevOpsClientError, parse_pr_url


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_WEBHOOK_URL", "http://testserver/webhooks/jira")
    monkeypatch.setenv("AZURE_DEVOPS_ORG", "testorg")
    monkeypatch.setenv("AZURE_DEVOPS_PROJECT", "testproject")
    monkeypatch.setenv("AZURE_DEVOPS_REPO_ID", "test-repo")
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "test-pat")


class TestParsePrUrl:
    def test_standard_url(self):
        url = "https://dev.azure.com/myorg/myproject/_git/myrepo/pullrequest/42"
        result = parse_pr_url(url)
        assert result == {"org": "myorg", "project": "myproject", "repo": "myrepo", "pr_id": 42}

    def test_visualstudio_url(self):
        url = "https://myorg.visualstudio.com/myproject/_git/myrepo/pullrequest/99"
        result = parse_pr_url(url)
        assert result == {"org": "myorg", "project": "myproject", "repo": "myrepo", "pr_id": 99}

    def test_case_insensitive_pr(self):
        url = "https://dev.azure.com/org/proj/_git/repo/PullRequest/7"
        result = parse_pr_url(url)
        assert result == {"org": "org", "project": "proj", "repo": "repo", "pr_id": 7}

    def test_invalid_url(self):
        assert parse_pr_url("https://example.com") is None


class TestAzureDevOpsClient:
    @pytest.mark.asyncio
    async def test_check_connection_not_configured(self, monkeypatch):
        monkeypatch.setenv("AZURE_DEVOPS_ORG", "")
        client = AzureDevOpsClient()
        result = await client.check_connection()
        assert result["connected"] is False
        assert "not configured" in result["details"]

    @pytest.mark.asyncio
    async def test_raises_when_unconfigured(self, monkeypatch):
        monkeypatch.setenv("AZURE_DEVOPS_ORG", "")
        client = AzureDevOpsClient()
        with pytest.raises(AzureDevOpsClientError, match="not configured"):
            await client._get("/test")

    @pytest.mark.asyncio
    async def test_check_connection_success(self, monkeypatch):
        async def mock_get(self, path, params=None):
            return {"value": [{"id": "repo-1"}]}
        monkeypatch.setattr(AzureDevOpsClient, "_get", mock_get)
        client = AzureDevOpsClient()
        result = await client.check_connection()
        assert result["connected"] is True

    @pytest.mark.asyncio
    async def test_get_pull_request(self, monkeypatch):
        async def mock_get(self, path, params=None):
            return {"pullRequestId": 42, "title": "Test PR", "status": "active"}
        monkeypatch.setattr(AzureDevOpsClient, "_get", mock_get)
        client = AzureDevOpsClient()
        pr = await client.get_pull_request(42)
        assert pr["pullRequestId"] == 42
        assert pr["title"] == "Test PR"

    @pytest.mark.asyncio
    async def test_get_pull_request_by_url(self, monkeypatch):
        async def mock_get(self, path, params=None):
            return {"pullRequestId": 42, "title": "URL PR", "status": "completed"}
        monkeypatch.setattr(AzureDevOpsClient, "_get", mock_get)
        client = AzureDevOpsClient()
        pr = await client.get_pull_request_by_url("https://dev.azure.com/org/proj/_git/repo/pullrequest/42")
        assert pr["pullRequestId"] == 42

    @pytest.mark.asyncio
    async def test_get_pipeline_run(self, monkeypatch):
        async def mock_get(self, path, params=None):
            return {"id": 100, "status": "completed", "result": "succeeded"}
        monkeypatch.setattr(AzureDevOpsClient, "_get", mock_get)
        client = AzureDevOpsClient()
        run = await client.get_pipeline_run(1, 100)
        assert run["result"] == "succeeded"

    @pytest.mark.asyncio
    async def test_get_pipeline_run_by_url(self, monkeypatch):
        calls = []

        async def mock_get(self, path, params=None):
            calls.append((path, params))
            return {"id": 55, "status": "inProgress", "result": None}

        monkeypatch.setattr(AzureDevOpsClient, "_get", mock_get)
        client = AzureDevOpsClient()
        run = await client.get_pipeline_run_by_url("https://dev.azure.com/org/proj/_build/results?buildId=55")
        assert run["id"] == 55
