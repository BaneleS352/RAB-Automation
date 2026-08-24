"""Tests for Teams webhook endpoint - integration removed.

This module has been updated to reflect the removal of the Teams
webhook endpoint as the team shifts to a different issue management and
monitoring platform.
"""

import pytest


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_WEBHOOK_URL", "http://testserver/webhooks/jira")