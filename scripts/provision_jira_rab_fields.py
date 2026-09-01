"""Create the Jira custom fields required by data.xml.

The script is idempotent: existing fields are reused by exact name. Jira admin
permissions are required. It does not change tickets; use the printed mappings
with the ticket migration/sync process after provisioning.

Usage: python scripts/provision_jira_rab_fields.py [--project TEST]
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import sys

import httpx
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

FIELDS = [
    ("Date/Time of Deployment", "JIRA_FIELD_DATE_TIME", "com.atlassian.jira.plugin.system.customfieldtypes:datetime", "com.atlassian.jira.plugin.system.customfieldtypes:datetimerange"),
    ("RAB Approver", "JIRA_FIELD_RAB_APPROVER", "com.atlassian.jira.plugin.system.customfieldtypes:textfield", "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher"),
    ("PR Link", "JIRA_FIELD_PR_LINK", "com.atlassian.jira.plugin.system.customfieldtypes:url", "com.atlassian.jira.plugin.system.customfieldtypes:exacttextsearcher"),
    ("Release Pipeline Link", "JIRA_FIELD_PIPELINE_LINK", "com.atlassian.jira.plugin.system.customfieldtypes:url", "com.atlassian.jira.plugin.system.customfieldtypes:exacttextsearcher"),
    ("Developer", "JIRA_FIELD_DEVELOPER", "com.atlassian.jira.plugin.system.customfieldtypes:textfield", "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher"),
    ("Team Lead", "JIRA_FIELD_TEAM_LEAD", "com.atlassian.jira.plugin.system.customfieldtypes:textfield", "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher"),
    ("Project Manager", "JIRA_FIELD_PM", "com.atlassian.jira.plugin.system.customfieldtypes:textfield", "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher"),
    ("QA", "JIRA_FIELD_QA", "com.atlassian.jira.plugin.system.customfieldtypes:textfield", "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher"),
    ("Rollback/Mitigation Details", "JIRA_FIELD_ROLLBACK_DETAILS", "com.atlassian.jira.plugin.system.customfieldtypes:textarea", "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher"),
    ("Deployment Instructions", "JIRA_FIELD_DEPLOYMENT_INSTRUCTIONS", "com.atlassian.jira.plugin.system.customfieldtypes:textarea", "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher"),
    ("Outcome Notes", "JIRA_FIELD_OUTCOME_NOTES", "com.atlassian.jira.plugin.system.customfieldtypes:textarea", "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher"),
    ("Rollback Strategy", "JIRA_FIELD_ROLLBACK_STRATEGY", "com.atlassian.jira.plugin.system.customfieldtypes:textarea", "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher"),
    ("Mitigation Strategy", "JIRA_FIELD_MITIGATION_STRATEGY", "com.atlassian.jira.plugin.system.customfieldtypes:textarea", "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher"),
    ("Related Release Reference", "JIRA_FIELD_RELATED_RELEASE_REFERENCE", "com.atlassian.jira.plugin.system.customfieldtypes:textfield", "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher"),
    ("Release Outcome", "JIRA_FIELD_RELEASE_OUTCOME", "com.atlassian.jira.plugin.system.customfieldtypes:textfield", "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher"),
    ("Environments", "JIRA_FIELD_ENVIRONMENTS", "com.atlassian.jira.plugin.system.customfieldtypes:textfield", "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher"),
    ("Development", "JIRA_FIELD_DEVELOPMENT", "com.atlassian.jira.plugin.system.customfieldtypes:textfield", "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher"),
    ("Parent Reference", "JIRA_FIELD_PARENT_REFERENCE", "com.atlassian.jira.plugin.system.customfieldtypes:textfield", "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher"),
    ("Sprint", "JIRA_FIELD_SPRINT", "com.atlassian.jira.plugin.system.customfieldtypes:textfield", "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher"),
]


async def main(project: str) -> None:
    base = os.getenv("JIRA_BASE_URL", "").rstrip("/")
    email = os.getenv("JIRA_EMAIL", "")
    token = os.getenv("JIRA_API_TOKEN", "")
    if not base or not email or not token:
        raise SystemExit("JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN are required")
    auth = httpx.BasicAuth(email, token)
    async with httpx.AsyncClient(timeout=30, auth=auth, headers={"Accept": "application/json", "Content-Type": "application/json"}) as client:
        response = await client.get(f"{base}/rest/api/3/field")
        response.raise_for_status()
        existing = {item["name"].strip().lower(): item for item in response.json()}
        mappings: dict[str, str] = {}
        for name, env_name, field_type, searcher_key in FIELDS:
            item = existing.get(name.lower())
            if item is None:
                response = await client.post(f"{base}/rest/api/3/field", json={
                    "name": name,
                    "description": f"RAB Automation field from data.xml for project {project}",
                    "type": field_type,
                    "searcherKey": searcher_key,
                })
                response.raise_for_status()
                item = response.json()
                print(f"created {name}: {item['id']}")
            else:
                print(f"exists  {name}: {item['id']}")
            mappings[env_name] = item["id"]
    print(f"\n# Jira project: {project}\n" + "\n".join(f"{key}={value}" for key, value in mappings.items()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=os.getenv("JIRA_PROJECT_KEY", "TEST"))
    args = parser.parse_args()
    asyncio.run(main(args.project))
