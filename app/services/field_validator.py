import logging
from dataclasses import dataclass, field

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    valid: bool
    missing_fields: list[str] = field(default_factory=list)
    detail: str = ""


REQUIRED_FIELDS = [
    ("Date/Time", "date_time"),
    ("RAB Approver", "rab_approver"),
    ("Assignee", "assignee"),
    ("Reporter", "reporter"),
    ("PR Link", "pr_link"),
    ("Pipeline Link", "pipeline_link"),
    ("Developer", "developer"),
    ("Team Lead", "team_lead"),
    ("PM", "pm"),
    ("QA", "qa"),
    ("Environment", "environment"),
    ("Rollback/Mitigation Details", "rollback_details"),
]


STANDARD_FIELD_KEYS = {
    "assignee": "assignee",
    "reporter": "reporter",
}


class FieldValidator:
    """Validates that required RAB fields are present on a Jira issue."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._build_field_map()

    def _build_field_map(self) -> None:
        self.field_map: dict[str, str | None] = {}
        for _, field_key in REQUIRED_FIELDS:
            if field_key in STANDARD_FIELD_KEYS:
                self.field_map[field_key] = STANDARD_FIELD_KEYS[field_key]
            else:
                custom = getattr(self.settings, f"JIRA_FIELD_{field_key.upper()}", None)
                self.field_map[field_key] = custom or None

    def extract_field_value(self, issue_data: dict, field_key: str) -> str | None:
        fields = issue_data.get("fields", {})
        mapped = self.field_map.get(field_key)
        if not mapped:
            return None
        if mapped in ("assignee", "reporter"):
            user = fields.get(mapped)
            return user.get("displayName") if user else None
        return fields.get(mapped)

    def validate(self, issue_data: dict) -> ValidationResult:
        missing: list[str] = []
        for display_name, field_key in REQUIRED_FIELDS:
            mapped = self.field_map.get(field_key)
            if mapped is None:
                logger.debug("Skipping '%s' — no field mapping configured", display_name)
                continue
            value = self.extract_field_value(issue_data, field_key)
            if not value:
                missing.append(display_name)

        if missing:
            detail = f"Missing required fields: {', '.join(missing)}"
            logger.warning("Validation failed: %s", detail)
            return ValidationResult(valid=False, missing_fields=missing, detail=detail)

        return ValidationResult(valid=True, detail="All required fields are present.")
