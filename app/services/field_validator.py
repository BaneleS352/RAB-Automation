"""Field validation for Jira issue fields required by the RAB process."""

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


STANDARD_FIELDS: set[str] = {"assignee", "reporter"}
# Backward compat alias — was previously an identity dict
STANDARD_FIELD_KEYS = {k: k for k in STANDARD_FIELDS}


class FieldValidator:
    """Validates that required RAB fields are present on a Jira issue."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._build_field_map()

    def _build_field_map(self) -> None:
        self.field_map: dict[str, str | None] = {}
        for _, field_key in REQUIRED_FIELDS:
            if field_key in STANDARD_FIELDS:
                self.field_map[field_key] = field_key
            else:
                custom = getattr(self.settings, f"JIRA_FIELD_{field_key.upper()}", None)
                # Use explicit None check to allow empty-string config to be distinguished from unset
                self.field_map[field_key] = custom if custom is not None and custom != "" else None

    def extract_field_value(self, issue_data: dict, field_key: str) -> str | None:
        fields = issue_data.get("fields", {})
        mapped = self.field_map.get(field_key)
        if mapped:
            if mapped in ("assignee", "reporter"):
                user = fields.get(mapped)
                val = user.get("displayName") if isinstance(user, dict) else None
                if val:
                    return val
                # Fall through to description fallback if assignee/reporter empty (common blank case)
            else:
                val = self._normalize(fields.get(mapped))
                if val:
                    return val
                # If mapped field exists but is empty, fall through to description fallback (was previously blank)
        # Fallback: try to parse from Jira description text when custom field not configured or empty.
        # This addresses the systemic "empty/not mapped" — description now contains the RAB block from populate script.
        desc_text = self._description_text(fields.get("description"))
        if desc_text:
            fallback = self._extract_from_description(desc_text, field_key)
            if fallback:
                return fallback
        # Also try standard 'environment' field as fallback for environment key when not mapped
        if field_key == "environment" and not mapped:
            env = self._normalize(fields.get("environment"))
            if env:
                return env
        return None

    @staticmethod
    def _description_text(adf: object) -> str:
        if not adf:
            return ""
        if isinstance(adf, str):
            return adf
        if isinstance(adf, dict):
            parts: list[str] = []
            for block in adf.get("content") or []:
                if isinstance(block, dict):
                    for inline in block.get("content") or []:
                        if isinstance(inline, dict) and inline.get("type") == "text":
                            parts.append(inline.get("text") or "")
                    parts.append("\n")
            return "".join(parts).strip()
        return str(adf)

    @staticmethod
    def _extract_from_description(text: str, field_key: str) -> str | None:
        """Parse RAB field values embedded in description text (e.g., 'PR Link: https://...')."""
        import re

        # Map logical keys to patterns found in the RAB details block
        patterns: dict[str, list[str]] = {
            "pr_link": [r"PR Link:\s*(.+)", r"PR:\s*(https?://\S+)"],
            "pipeline_link": [r"Pipeline Link:\s*(.+)", r"Pipeline:\s*(https?://\S+)"],
            "rab_approver": [r"RAB Approver:\s*(.+)", r"Approver:\s*(.+)"],
            "developer": [r"Developer:\s*(.+)", r"Dev:\s*(.+)"],
            "team_lead": [r"Team Lead:\s*(.+)", r"TeamLead:\s*(.+)"],
            "pm": [r"\bPM:\s*(.+)", r"Project Manager:\s*(.+)"],
            "qa": [r"\bQA:\s*(.+)", r"QA Engineer:\s*(.+)"],
            "environment": [r"Environment:\s*(.+)", r"Env:\s*(.+)"],
            "rollback_details": [r"Rollback(?:/Mitigation)?:\s*(.+)", r"Mitigation:\s*(.+)"],
            "date_time": [r"Date/Time:\s*(.+)", r"Date:\s*(.+)"],
        }
        candidates = patterns.get(field_key, [])
        for pat in candidates:
            m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
            if m:
                val = m.group(1).strip().splitlines()[0].strip()
                # Strip trailing punctuation that is not part of URL
                val = val.rstrip(".,;")
                if val and val.lower() not in ("n/a", "none", "-", "—"):
                    return val
        return None

    @staticmethod
    def _normalize(value: object) -> str | None:
        """Flatten common Jira custom field shapes into a single string."""
        if value is None:
            return None
        if isinstance(value, dict):
            raw = value.get("displayName") or value.get("value") or value.get("name")
            if isinstance(raw, str):
                raw = raw.strip()
                return raw or None
            return str(raw).strip() or None if raw is not None else None
        if isinstance(value, list):
            if not value:
                return None
            parts: list[str] = []
            for item in value:
                if item is None:
                    continue
                if isinstance(item, dict):
                    part = item.get("displayName") or item.get("value") or item.get("name")
                else:
                    part = str(item)
                if isinstance(part, str) and part.strip():
                    parts.append(part.strip())
            return ", ".join(parts) if parts else None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return str(value).strip() or None

    def validate(self, issue_data: dict) -> ValidationResult:
        missing: list[str] = []
        for display_name, field_key in REQUIRED_FIELDS:
            value = self.extract_field_value(issue_data, field_key)
            mapped = self.field_map.get(field_key)
            if not value or (isinstance(value, str) and not value.strip()):
                # Only warn about missing mapping when fallback also failed — previously was silent skip (same class as blank-details)
                if mapped is None:
                    logger.info("Field '%s' has no JIRA_FIELD_* mapping and no description fallback — will be reported as missing", display_name)
                missing.append(display_name)
            elif mapped is None and value:
                logger.debug("Field '%s' satisfied via description fallback (no JIRA_FIELD_* mapping): %s", display_name, value[:60])

        if missing:
            detail = f"Missing required fields: {', '.join(missing)}"
            logger.warning("Validation failed: %s", detail)
            return ValidationResult(valid=False, missing_fields=missing, detail=detail)

        return ValidationResult(valid=True, detail="All required fields are present.")
