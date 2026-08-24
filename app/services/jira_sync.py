"""Jira project sync — ensures all Jira issues are monitored regardless of creation method."""

import logging
from dataclasses import dataclass

from app.config import get_settings
from app.repositories.rab_repository import RabRepository
from app.services.field_validator import FieldValidator
from app.services.jira_client import JiraClient, JiraClientError

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
        summary = issue.get("fields", {}).get("summary", "") or ""
        data: dict = {
            "summary": summary,
            "validation_result": validation.detail if not validation.valid else "",
            "status": "validated" if validation.valid else "validation_failed",
        }
        # Preserve approval/meeting state if already tracked — don't overwrite with pending
        if existing:
            # Only update summary/validation, keep status if already in approval flow
            if existing.get("status") in ("sdl_requested", "sdm_requested", "sdl_approved", "sdm_approved", "sdl_rejected", "sdm_rejected", "release_ready", "meeting_scheduled"):
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
