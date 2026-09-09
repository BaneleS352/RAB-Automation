"""Single live-Jira hydration entry point for UI, APIs, and webhooks."""

import json
from typing import Any

from app.repositories.rab_repository import RabRepository
from app.services.field_validator import FieldValidator, REQUIRED_FIELDS
from app.services.jira_client import JiraClient
from app.services.jira_fields import adf_to_text


def snapshot_issue(issue: dict, validator: FieldValidator | None = None) -> dict[str, Any]:
    validator = validator or FieldValidator()
    fields = issue.get("fields", {}) or {}
    obj = lambda key: fields.get(key) if isinstance(fields.get(key), dict) else {}
    structure_fn = getattr(validator, "extract_ticket_structure", None)
    structure = structure_fn(issue) if callable(structure_fn) else {}
    rab_fields = {key: validator.extract_field_value(issue, key) for _, key in REQUIRED_FIELDS}
    return {"summary": fields.get("summary", "") or "", "description": adf_to_text(fields.get("description"))[:2000], "priority": obj("priority").get("name", ""), "issuetype": obj("issuetype").get("name", ""), "jira_status": obj("status").get("name", ""), "labels": ", ".join(fields.get("labels") or [])[:500], "reporter": obj("reporter").get("displayName") or obj("reporter").get("accountId", ""), "creator": (obj("creator") or obj("reporter")).get("displayName", ""), "assignee": obj("assignee").get("displayName") or obj("assignee").get("accountId", ""), "jira_updated": fields.get("updated") or fields.get("created") or "", "raw_fields": json.dumps({"rab_fields": rab_fields, "ticket_structure": structure, "field_map": getattr(validator, "field_map", {})}, ensure_ascii=False)[:4000], **{key if key != "parent" else "parent_reference": value or "" for key, value in structure.items()}}


async def hydrate_issue(issue_key: str, *, client: JiraClient | None = None, repo: RabRepository | None = None) -> dict:
    """Fetch the authoritative Jira issue and persist its current Jira snapshot."""
    client = client or JiraClient()
    issue = await client.get_issue(issue_key)
    if not issue or not issue.get("key"):
        raise ValueError(f"Jira returned no issue for {issue_key}")
    if repo is not None:
        await repo.upsert_record(issue_key, snapshot_issue(issue))
        await repo.mark_jira_seen(issue_key)
    return issue
