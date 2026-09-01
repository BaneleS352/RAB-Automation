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
        from app.services.jira_fields import adf_to_text

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
        desc_text = adf_to_text(fields.get("description"))
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
    def _extract_from_description(text: str, field_key: str) -> str | None:
        """Parse RAB field values embedded in description text (e.g., 'PR Link: https://...')."""
        import re

        # Map logical keys to patterns found in the RAB details block — anchored to line start to avoid capturing trailing fields
        patterns: dict[str, list[str]] = {
            "pr_link": [r"(?:^|\n)PR Link:\s*([^\n]+)", r"(?:^|\n)PR:\s*(https?://\S+)"],
            "pipeline_link": [r"(?:^|\n)Pipeline Link:\s*([^\n]+)", r"(?:^|\n)Pipeline:\s*(https?://\S+)"],
            "rab_approver": [r"(?:^|\n)RAB Approver:\s*([^\n]+)", r"(?:^|\n)Approver:\s*([^\n]+)"],
            "developer": [r"(?:^|\n)Developer:\s*([^\n]+)", r"(?:^|\n)Dev:\s*([^\n]+)"],
            "team_lead": [r"(?:^|\n)Team Lead:\s*([^\n]+)", r"(?:^|\n)TeamLead:\s*([^\n]+)"],
            "pm": [r"(?:^|\n)PM:\s*([^\n]+)", r"(?:^|\n)Project Manager:\s*([^\n]+)"],
            "qa": [r"(?:^|\n)QA:\s*([^\n]+)", r"(?:^|\n)QA Engineer:\s*([^\n]+)"],
            "environment": [r"(?:^|\n)Environment:\s*([^\n]+)", r"(?:^|\n)Env:\s*([^\n]+)"],
            "rollback_details": [r"(?:^|\n)Rollback(?:/Mitigation)?:\s*([^\n]+)", r"(?:^|\n)Mitigation:\s*([^\n]+)"],
            "date_time": [r"(?:^|\n)Date/Time:\s*([^\n]+)", r"(?:^|\n)Date:\s*([^\n]+)"],
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

    def audit(self, issue_data: dict) -> dict[str, list[str] | str]:
        """Advisory audit — note which RAB fields are present vs missing (per data structure.drawio.html: GET and NOTE, not hard FAIL)."""
        present: list[str] = []
        missing: list[str] = []
        present_values: dict[str, str] = {}
        for display_name, field_key in REQUIRED_FIELDS:
            value = self.extract_field_value(issue_data, field_key)
            if value and isinstance(value, str) and value.strip():
                present.append(display_name)
                present_values[display_name] = value[:120]
            else:
                missing.append(display_name)
        return {"present": present, "missing": missing, "present_values": present_values}

    def validate(self, issue_data: dict) -> ValidationResult:
        audit = self.audit(issue_data)
        missing: list[str] = audit["missing"]  # type: ignore
        present: list[str] = audit["present"]  # type: ignore
        present_values: dict[str, str] = audit["present_values"]  # type: ignore

        # Log mapping fallback usage (was silent blank before) — reuse audit results to avoid double parse (was 24 ADF parses)
        for display_name, field_key in REQUIRED_FIELDS:
            mapped = self.field_map.get(field_key)
            in_present = display_name in present
            if mapped is None and in_present:
                logger.debug("Field '%s' satisfied via description fallback (no JIRA_FIELD_* mapping): %s", display_name, present_values.get(display_name, "")[:60])
            elif mapped is None and not in_present:
                logger.info("Field '%s' has no JIRA_FIELD_* mapping and no description fallback — will be reported as missing", display_name)

        # Advisory mode (default, per user request + drawio): GET ticket and NOTE present/missing, do not block workflow
        # Strict mode (RAB_STRICT_VALIDATION=True) retains old hard-fail behavior.
        strict = bool(getattr(self.settings, "RAB_STRICT_VALIDATION", False))
        if missing:
            if strict:
                detail = f"Missing required fields: {', '.join(missing)}"
                logger.warning("Validation failed (strict): %s", detail)
                return ValidationResult(valid=False, missing_fields=missing, detail=detail)
            # Advisory: always valid, but detail notes present/missing (this fixes blank-details by surfacing completeness)
            present_str = ", ".join(present) if present else "none"
            missing_str = ", ".join(missing) if missing else "none"
            detail = f"RAB audit — Present ({len(present)}/12): {present_str} | Missing ({len(missing)}/12): {missing_str} (advisory, workflow continues)"
            logger.info("RAB audit (advisory): %s", detail)
            return ValidationResult(valid=True, missing_fields=missing, detail=detail)

        return ValidationResult(valid=True, detail="All 12 RAB fields present — Present (12/12): " + ", ".join(present))
