"""Tests for the FieldValidator service."""

import pytest
from app.services.field_validator import FieldValidator, REQUIRED_FIELDS


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_WEBHOOK_URL", "http://testserver/webhooks/jira")
    monkeypatch.setenv("APP_ENV", "test")


class TestFieldValidator:
    def test_all_fields_present_passes(self, monkeypatch):
        for _, key in REQUIRED_FIELDS:
            if key not in ("assignee", "reporter"):
                monkeypatch.setenv(f"JIRA_FIELD_{key.upper()}", f"customfield_{key}")

        validator = FieldValidator()
        fields = {
            "assignee": {"displayName": "Alice"},
            "reporter": {"displayName": "Bob"},
            "customfield_pr_link": "https://github.com/example/pr/1",
            "customfield_pipeline_link": "https://pipeline.example.com/run/1",
            "customfield_rab_approver": "Charlie",
            "customfield_developer": "Alice",
            "customfield_team_lead": "Dave",
            "customfield_pm": "Eve",
            "customfield_qa": "Frank",
            "customfield_environment": "Production",
            "customfield_rollback_details": "Revert commit abc123",
            "customfield_date_time": "2026-07-16T10:00:00",
        }
        result = validator.validate({"fields": fields})
        assert result.valid is True
        assert result.missing_fields == []

    def test_missing_fields_fails(self, monkeypatch):
        for _, key in REQUIRED_FIELDS:
            if key not in ("assignee", "reporter"):
                monkeypatch.setenv(f"JIRA_FIELD_{key.upper()}", f"customfield_{key}")

        validator = FieldValidator()
        fields = {
            "assignee": {"displayName": "Alice"},
            "reporter": {"displayName": "Bob"},
        }
        result = validator.validate({"fields": fields})
        assert result.valid is False
        assert len(result.missing_fields) > 0
        assert "PR Link" in result.missing_fields

    def test_no_mappings_configured(self, monkeypatch):
        validator = FieldValidator()
        fields = {
            "assignee": {"displayName": "Alice"},
            "reporter": {"displayName": "Bob"},
        }
        result = validator.validate({"fields": fields})
        assert result.valid is True

    def test_assignee_and_reporter_checked(self, monkeypatch):
        validator = FieldValidator()
        result = validator.validate({"fields": {}})
        assert result.valid is False
        assert "Assignee" in result.missing_fields
        assert "Reporter" in result.missing_fields

        monkeypatch.setenv("JIRA_FIELD_RAB_APPROVER", "customfield_rab_approver")
        validator2 = FieldValidator()
        fields = {
            "assignee": {"displayName": "Alice"},
            "reporter": {"displayName": "Bob"},
        }
        result2 = validator2.validate({"fields": fields})
        assert result2.valid is False
        assert "RAB Approver" in result2.missing_fields
