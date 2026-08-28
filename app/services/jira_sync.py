"""Jira project sync — ensures all Jira issues are monitored regardless of creation method."""

import json
import logging
from dataclasses import dataclass

from app.config import get_settings
from app.repositories.rab_repository import RabRepository
from app.services.field_validator import FieldValidator
from app.services.jira_client import JiraClient, JiraClientError
from app.services.status_codes import FLOW_STATUSES


def _adf_to_text(adf: object) -> str:
    """Flatten Atlassian Document Format (description) to plain text."""
    if not adf:
        return ""
    if isinstance(adf, str):
        return adf
    if isinstance(adf, dict):
        # ADF doc: {"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"..."}]}]}
        parts: list[str] = []
        for block in adf.get("content") or []:
            if isinstance(block, dict):
                for inline in block.get("content") or []:
                    if isinstance(inline, dict) and inline.get("type") == "text":
                        parts.append(inline.get("text") or "")
                    elif isinstance(inline, dict) and "text" in inline:
                        parts.append(str(inline["text"]))
                # Separate blocks with newline
                parts.append("\n")
        text = "".join(parts).strip()
        return text if text else json.dumps(adf)[:500] if adf else ""
    return str(adf)[:1000]


def _extract_rich_fields(issue: dict, field_validator: FieldValidator) -> dict:
    """Extract persistable rich fields from a Jira issue dict."""
    fields = issue.get("fields", {}) or {}
    # Core rich fields that exist on every issue — previously not persisted (caused blank details)
    summary = fields.get("summary", "") or ""
    description = _adf_to_text(fields.get("description"))
    priority = (fields.get("priority") or {}).get("name", "") if isinstance(fields.get("priority"), dict) else ""
    issuetype = (fields.get("issuetype") or {}).get("name", "") if isinstance(fields.get("issuetype"), dict) else ""
    jira_status = (fields.get("status") or {}).get("name", "") if isinstance(fields.get("status"), dict) else ""
    labels = ", ".join(fields.get("labels") or []) if isinstance(fields.get("labels"), list) else ""
    reporter_data = fields.get("reporter") or {}
    reporter = reporter_data.get("displayName") or reporter_data.get("accountId") or "" if isinstance(reporter_data, dict) else ""
    creator_data = fields.get("creator") or fields.get("reporter") or {}
    creator = creator_data.get("displayName") or creator_data.get("accountId") or "" if isinstance(creator_data, dict) else ""
    assignee_data = fields.get("assignee") or {}
    assignee = assignee_data.get("displayName") or assignee_data.get("accountId") or "" if isinstance(assignee_data, dict) else ""
    jira_updated = fields.get("updated") or fields.get("created") or ""

    # RAB required fields snapshot — explains why validation says missing vs blank
    rab_snapshot: dict[str, str | None] = {}
    for display, key in field_validator.REQUIRED_FIELDS if hasattr(field_validator, "REQUIRED_FIELDS") else []:
        # Use field_map + extract to capture actual value or None
        try:
            rab_snapshot[key] = field_validator.extract_field_value(issue, key)
        except Exception:
            rab_snapshot[key] = None
    # Fallback if REQUIRED_FIELDS not on instance (module-level)
    if not rab_snapshot:
        try:
            from app.services.field_validator import REQUIRED_FIELDS

            for display, key in REQUIRED_FIELDS:
                try:
                    rab_snapshot[key] = field_validator.extract_field_value(issue, key)
                except Exception:
                    rab_snapshot[key] = None
        except Exception:
            pass

    raw_fields = json.dumps(
        {
            "rab_fields": rab_snapshot,
            "field_map": getattr(field_validator, "field_map", {}),
            "description_present": bool(description),
            "labels": labels,
        },
        ensure_ascii=False,
    )[:4000]

    return {
        "summary": summary,
        "description": description[:2000],
        "priority": priority,
        "issuetype": issuetype,
        "jira_status": jira_status,
        "labels": labels[:500],
        "reporter": reporter,
        "creator": creator,
        "assignee": assignee,
        "jira_updated": jira_updated,
        "raw_fields": raw_fields,
    }

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    synced: int = 0
    created: int = 0
    updated: int = 0
    failed: int = 0
    errors: list[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class JiraSyncService:
    """Syncs all issues from a Jira project into the local audit store."""

    def __init__(
        self,
        jira_client: JiraClient | None = None,
        field_validator: FieldValidator | None = None,
        rab_repo: RabRepository | None = None,
    ) -> None:
        self.jira_client = jira_client or JiraClient()
        self.field_validator = field_validator or FieldValidator()
        self.rab_repo = rab_repo or RabRepository()
        self.settings = get_settings()

    async def sync_issue(self, issue: dict) -> str:
        """Sync a single Jira issue dict into rab_records. Returns status."""
        issue_key = issue.get("key")
        if not issue_key:
            return "skipped_no_key"
        # Existing record check
        existing = await self.rab_repo.get_record(issue_key)
        # Validate via field_validator (uses same logic as webhook)
        validation = self.field_validator.validate(issue)
        rich = _extract_rich_fields(issue, self.field_validator)
        data: dict = {
            "summary": rich["summary"],
            "description": rich["description"],
            "priority": rich["priority"],
            "issuetype": rich["issuetype"],
            "jira_status": rich["jira_status"],
            "labels": rich["labels"],
            "reporter": rich["reporter"],
            "creator": rich["creator"],
            "assignee": rich["assignee"],
            "jira_updated": rich["jira_updated"],
            "raw_fields": rich["raw_fields"],
            "validation_result": validation.detail if not validation.valid else "",
            "status": "validated" if validation.valid else "validation_failed",
        }
        # Preserve approval/meeting state if already tracked — don't overwrite status
        # if the issue is already in an approval/flow state
        if existing:
            # Only update summary/validation, keep existing status if already
            # in an approval/flow state (avoid resetting to validated/validation_failed)
            if existing.get("status") in FLOW_STATUSES:
                data.pop("status", None)
            await self.rab_repo.upsert_record(issue_key, data)
            return "updated"
        else:
            # New issue — create record; if validated, also seed approval state as pending SDL so it appears in pipeline
            await self.rab_repo.upsert_record(issue_key, data)
            return "created"

    async def sync_project(self, project_key: str | None = None) -> SyncResult:
        """Sync all issues for project_key (defaults to JIRA_PROJECT_KEY)."""
        key = project_key or self.settings.JIRA_PROJECT_KEY
        if not key:
            return SyncResult(failed=1, errors=["JIRA_PROJECT_KEY not configured — set it to enable full project sync."])
        if not self.jira_client.base_url or not self.jira_client.email or not self.jira_client.api_token:
            return SyncResult(failed=1, errors=["Jira API not configured — cannot sync."])
        result = SyncResult()
        try:
            issues = await self.jira_client.list_project_issues(key)
        except JiraClientError as e:
            result.failed = 1
            result.errors.append(str(e))
            logger.error("Jira sync failed for project %s: %s", key, e)
            return result

        for issue in issues:
            try:
                status = await self.sync_issue(issue)
                result.synced += 1
                if status == "created":
                    result.created += 1
                elif status == "updated":
                    result.updated += 1
            except Exception as e:
                result.failed += 1
                result.errors.append(f"{issue.get('key')}: {e}")
                logger.exception("Failed to sync issue %s", issue.get("key"))

        logger.info("Jira sync complete project=%s synced=%d created=%d updated=%d failed=%d", key, result.synced, result.created, result.updated, result.failed)
        return result

    async def sync_all(self) -> SyncResult:
        """Sync using configured project; if no project, sync via JQL `order by updated desc` with no project filter (last 100 issues)."""
        if self.settings.JIRA_PROJECT_KEY:
            return await self.sync_project(self.settings.JIRA_PROJECT_KEY)
        # Fallback: try to list recent issues without project filter (requires Jira perms)
        try:
            data = await self.jira_client.search_issues("ORDER BY updated DESC", max_results=100)
            issues = data.get("issues", [])
            result = SyncResult()
            for issue in issues:
                try:
                    status = await self.sync_issue(issue)
                    result.synced += 1
                    if status == "created":
                        result.created += 1
                    elif status == "updated":
                        result.updated += 1
                except Exception as e:
                    result.failed += 1
                    result.errors.append(str(e))
            return result
        except JiraClientError as e:
            return SyncResult(failed=1, errors=[str(e)])
