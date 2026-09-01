"""Populate the provisioned RAB custom fields for every issue in a Jira project."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()

from app.services.field_validator import FieldValidator
from app.services.jira_client import JiraClient, JiraClientError

FIELD_MAP = {
    "date_time": "JIRA_FIELD_DATE_TIME", "rab_approver": "JIRA_FIELD_RAB_APPROVER",
    "pr_link": "JIRA_FIELD_PR_LINK", "pipeline_link": "JIRA_FIELD_PIPELINE_LINK",
    "developer": "JIRA_FIELD_DEVELOPER", "team_lead": "JIRA_FIELD_TEAM_LEAD",
    "pm": "JIRA_FIELD_PM", "qa": "JIRA_FIELD_QA", "environment": "JIRA_FIELD_ENVIRONMENT",
    "rollback_details": "JIRA_FIELD_ROLLBACK_DETAILS", "deployment_instructions": "JIRA_FIELD_DEPLOYMENT_INSTRUCTIONS",
    "outcome_notes": "JIRA_FIELD_OUTCOME_NOTES", "rollback_strategy": "JIRA_FIELD_ROLLBACK_STRATEGY",
    "mitigation_strategy": "JIRA_FIELD_MITIGATION_STRATEGY", "related_release_reference": "JIRA_FIELD_RELATED_RELEASE_REFERENCE",
    "release_outcome": "JIRA_FIELD_RELEASE_OUTCOME", "environments": "JIRA_FIELD_ENVIRONMENTS",
    "development": "JIRA_FIELD_DEVELOPMENT", "parent": "JIRA_FIELD_PARENT_REFERENCE", "sprint": "JIRA_FIELD_SPRINT",
}


async def main(project: str) -> None:
    client = JiraClient()
    validator = FieldValidator()
    issues = await client.list_project_issues(project, max_results=100)
    updated = 0
    skipped = 0
    for issue in issues:
        # Project search responses may contain only summary/key; fetch the
        # complete issue so custom fields and the RAB description are available.
        try:
            issue = await client.get_issue(issue["key"])
        except JiraClientError as exc:
            print(f"failed  {issue.get('key')}: {exc}")
            continue
        fields = issue.get("fields", {}) or {}
        values = {key: validator.extract_field_value(issue, key) for key in (
            "date_time", "rab_approver", "assignee", "reporter", "pr_link", "pipeline_link",
            "developer", "team_lead", "pm", "qa", "environment", "rollback_details")}
        values.update(validator.extract_ticket_structure(issue))
        payload = {}
        for logical, env_name in FIELD_MAP.items():
            field_id = os.getenv(env_name, "").strip()
            value = values.get(logical)
            if field_id and value:
                payload[field_id] = value
        if not payload:
            skipped += 1
            print(f"skipped {issue.get('key')}: no populated RAB values found")
            continue
        try:
            await client.update_issue(issue["key"], payload)
            updated += 1
            print(f"updated {issue['key']} ({len(payload)} fields)")
        except JiraClientError as exc:
            print(f"failed  {issue.get('key')}: {exc}")
    print(f"Migration complete: {updated} updated, {skipped} skipped, {len(issues)} total")


if __name__ == "__main__":
    asyncio.run(main(os.getenv("JIRA_PROJECT_KEY", "TEST")))
