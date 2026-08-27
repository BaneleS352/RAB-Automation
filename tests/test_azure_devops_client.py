"""Tests for Azure DevOps client - integration removed.

This module has been updated to reflect the removal of the Azure DevOps
integration as the team shifts to a different issue management and
monitoring platform.
"""

import pytest


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_WEBHOOK_URL", "http://testserver/webhooks/jira")


class TestAzureDevOpsRemoved:
    """Verify Azure DevOps integration is disabled."""

    def test_azure_devops_not_in_health(self) -> None:
        """Health endpoint should not report azure_devops status."""
        from app.api.health import _check_services
        import asyncio

        services = asyncio.run(_check_services())
        assert "azure_devops" not in services

    def test_azure_devops_not_in_dashboard(self) -> None:
        """Dashboard should not check azure_devops connection."""
        from app.api.dashboard import _check_connection_status
        import asyncio

        services = asyncio.run(_check_connection_status())
        assert "azure_devops" not in services