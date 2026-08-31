"""Shared config warnings — single source for health and dashboard (was duplicated)."""
from app.config import get_settings

def get_config_warnings() -> list[str]:
    s = get_settings()
    warns: list[str] = []
    if not s.JIRA_PROJECT_KEY:
        warns.append("JIRA_PROJECT_KEY empty — sync falls back to unfiltered 'ORDER BY updated DESC' (cross-project, first 100)")
    field_vars = [
        "JIRA_FIELD_DATE_TIME", "JIRA_FIELD_RAB_APPROVER", "JIRA_FIELD_PR_LINK", "JIRA_FIELD_PIPELINE_LINK",
        "JIRA_FIELD_DEVELOPER", "JIRA_FIELD_TEAM_LEAD", "JIRA_FIELD_PM", "JIRA_FIELD_QA",
        "JIRA_FIELD_ENVIRONMENT", "JIRA_FIELD_ROLLBACK_DETAILS",
    ]
    missing = sum(1 for v in field_vars if not getattr(s, v, ""))
    if missing >= 8:
        warns.append(f"{missing}/10 JIRA_FIELD_* mappings empty — validator now uses description fallback (was previously blank); set customfield IDs to use native fields")
    elif missing:
        warns.append(f"{missing}/10 JIRA_FIELD_* mappings empty — description fallback active for those fields")
    if not any([s.JIRA_TRANSITION_VALIDATE, s.JIRA_TRANSITION_REQUEST_APPROVAL, s.JIRA_TRANSITION_APPROVE, s.JIRA_TRANSITION_REJECT]):
        warns.append("All JIRA_TRANSITION_* empty — Jira issue status will never transition (was dead code before fix)")
    # Advisory mode info
    if not getattr(s, "RAB_STRICT_VALIDATION", False):
        warns.append("RAB_STRICT_VALIDATION=false — advisory GET-and-NOTE mode (missing RAB fields do not block workflow)")
    return warns
