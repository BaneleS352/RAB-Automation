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
        # Strict mode: missing fields should hard-fail (advisory is tested separately)
        monkeypatch.setenv("RAB_STRICT_VALIDATION", "true")
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
        # When no JIRA_FIELD_* mappings are set, validator now falls back to parsing description/environment.
        # With only assignee/reporter and no description block, all 10 custom fields are missing → should fail in strict mode (was previously silent skip → blank)
        monkeypatch.setenv("RAB_STRICT_VALIDATION", "true")
        validator = FieldValidator()
        fields = {
            "assignee": {"displayName": "Alice"},
            "reporter": {"displayName": "Bob"},
        }
        result = validator.validate({"fields": fields})
        assert result.valid is False
        assert "PR Link" in result.missing_fields

    def test_no_mappings_but_description_fallback_passes(self, monkeypatch):
        # New fallback: when JIRA_FIELD_* empty, description RAB block satisfies validation (fixes blank-details without customfields)
        validator = FieldValidator()
        fields = {
            "assignee": {"displayName": "Alice"},
            "reporter": {"displayName": "Bob"},
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": "RAB Details:\n- Date/Time: 2026-08-28T11:00:00Z\n- RAB Approver: approver@example.com\n- PR Link: https://github.com/example/pr/1\n- Pipeline Link: https://pipeline.example.com/1\n- Developer: dev@example.com\n- Team Lead: lead@example.com\n- PM: pm@example.com\n- QA: qa@example.com\n- Environment: staging\n- Rollback/Mitigation: revert",
                            }
                        ],
                    }
                ],
            },
            "environment": "staging",  # also satisfies via standard field fallback
        }
        result = validator.validate({"fields": fields})
        assert result.valid is True

    def test_assignee_and_reporter_checked(self, monkeypatch):
        monkeypatch.setenv("RAB_STRICT_VALIDATION", "true")
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

    def test_person_object_field_is_normalized(self, monkeypatch):
        monkeypatch.setenv("JIRA_FIELD_RAB_APPROVER", "customfield_rab_approver")
        validator = FieldValidator()
        # Provide description fallback for the other 9 required fields (was previously skipped → blank)
        fields = {
            "assignee": {"displayName": "Alice"},
            "reporter": {"displayName": "Bob"},
            "customfield_rab_approver": {"displayName": "Charlie"},
            "description": {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Date/Time: 2026-08-28\nPR Link: https://example.com/pr\nPipeline Link: https://example.com/pipe\nDeveloper: dev\nTeam Lead: lead\nPM: pm\nQA: qa\nEnvironment: staging\nRollback/Mitigation: revert"}]}],
            },
            "environment": "staging",
        }
        result = validator.validate({"fields": fields})
        assert result.valid is True
        # Also verify normalization extracts displayName
        assert validator.extract_field_value({"fields": fields}, "rab_approver") == "Charlie"

    def test_empty_person_object_field_counts_as_missing(self, monkeypatch):
        monkeypatch.setenv("RAB_STRICT_VALIDATION", "true")
        monkeypatch.setenv("JIRA_FIELD_RAB_APPROVER", "customfield_rab_approver")
        validator = FieldValidator()
        fields = {
            "assignee": {"displayName": "Alice"},
            "reporter": {"displayName": "Bob"},
            "customfield_rab_approver": {},
        }
        result = validator.validate({"fields": fields})
        assert result.valid is False
        assert "RAB Approver" in result.missing_fields

    def test_option_object_field_is_normalized(self, monkeypatch):
        monkeypatch.setenv("JIRA_FIELD_ENVIRONMENT", "customfield_environment")
        validator = FieldValidator()
        fields = {
            "assignee": {"displayName": "Alice"},
            "reporter": {"displayName": "Bob"},
            "customfield_environment": {"value": "Production"},
            "description": {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Date/Time: 2026-08-28\nRAB Approver: approver\nPR Link: https://example.com/pr\nPipeline Link: https://example.com/pipe\nDeveloper: dev\nTeam Lead: lead\nPM: pm\nQA: qa\nRollback/Mitigation: revert"}]}],
            },
        }
        result = validator.validate({"fields": fields})
        assert result.valid is True
        assert validator.extract_field_value({"fields": fields}, "environment") == "Production"

    def test_multi_value_list_is_joined(self, monkeypatch):
        monkeypatch.setenv("JIRA_FIELD_ENVIRONMENT", "customfield_environment")
        validator = FieldValidator()
        fields = {
            "assignee": {"displayName": "Alice"},
            "reporter": {"displayName": "Bob"},
            "customfield_environment": [
                {"value": "Production"},
                {"value": "Staging"},
                {"value": ""},
                None,
            ],
            "description": {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Date/Time: 2026-08-28\nRAB Approver: approver\nPR Link: https://example.com/pr\nPipeline Link: https://example.com/pipe\nDeveloper: dev\nTeam Lead: lead\nPM: pm\nQA: qa\nRollback/Mitigation: revert"}]}],
            },
        }
        result = validator.validate({"fields": fields})
        assert result.valid is True
        assert validator.extract_field_value({"fields": fields}, "environment") == "Production, Staging"

    def test_all_empty_list_values_count_as_missing(self, monkeypatch):
        monkeypatch.setenv("RAB_STRICT_VALIDATION", "true")
        monkeypatch.setenv("JIRA_FIELD_ENVIRONMENT", "customfield_environment")
        validator = FieldValidator()
        fields = {
            "assignee": {"displayName": "Alice"},
            "reporter": {"displayName": "Bob"},
            "customfield_environment": [{"value": ""}, {"value": ""}],
        }
        result = validator.validate({"fields": fields})
        assert result.valid is False
        assert "Environment" in result.missing_fields
