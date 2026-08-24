"""Tests for Teams client and card templates - integration removed.

This module has been updated to reflect the removal of the Teams
integration as the team shifts to a different issue management and
monitoring platform.
"""

import json

import pytest


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_WEBHOOK_URL", "http://testserver/webhooks/jira")