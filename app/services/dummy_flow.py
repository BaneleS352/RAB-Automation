"""Demo Lab scenarios backed exclusively by live Jira tickets."""

import logging
import re
from dataclasses import dataclass, field

from app.repositories.rab_repository import RabRepository
from app.services.approval_service import ApprovalService
from app.services.rab_orchestrator import RabOrchestrator
from app.services.jira_client import JiraClient
from app.services.field_validator import FieldValidator
from app.services.jira_hydration import hydrate_issue
from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class DummyFlowResult:
    issue_key: str
    steps: list[dict] = field(default_factory=list)
    status: str = "ok"


class _DemoPartialValidator:
    """Validator that simulates advisory validated_with_notes — only 4/12 present per drawio Power Automate check."""
    def validate(self, issue_data: dict):
        missing = ["Date/Time", "Developer", "PM", "QA", "Rollback/Mitigation Details", "Environment", "Pipeline Link", "RAB Approver"]
        # In advisory mode this is valid True with missing notes; in strict it would be valid False
        detail = f"RAB audit — Present (4/12): RAB Approver, PR Link, Pipeline Link, Team Lead | Missing (8/12): {', '.join(missing)} (advisory, workflow continues)"
        return type("V", (), {"valid": True, "detail": detail, "missing_fields": missing})()
    def extract_field_value(self, issue_data: dict, field_key: str):
        # Only the 4 Power Automate fields + assignee/reporter are considered present
        present = {"rab_approver": "sdl@example.com", "pr_link": "https://example.com/pr", "pipeline_link": "https://example.com/pipe", "team_lead": "lead@example.com", "assignee": "Demo Dev", "reporter": "Demo PM", "environment": "staging"}
        return present.get(field_key)


class DummyFlowService:
    """Runs Demo Lab scenarios against live Jira; local-only tickets are disabled."""

    def __init__(self, issue_key: str = "", summary: str = "Demo release ticket") -> None:
        # The demo key is an internal, stable correlation label only. Keep it
        # stable so demo_live_keys can reuse the same live Jira issue; Jira's
        # generated TEST-* key remains the only user-facing issue key.
        self.issue_key = issue_key
        self.summary = summary
        self.creator_name = "Demo Creator"
        self.approval_service = ApprovalService()
        self.rab_repo = RabRepository()
        settings = get_settings()
        jira_client = JiraClient()
        self.jira_client = jira_client
        if not jira_client.base_url or not jira_client.email or not jira_client.api_token:
            raise RuntimeError("Demo Lab requires configured Jira credentials; local-only synthetic tickets are disabled")
        validator: object = FieldValidator()
        self._real_project = settings.JIRA_PROJECT_KEY or "TEST"

        self.orchestrator = RabOrchestrator(
            jira_client=jira_client,
            field_validator=validator,  # type: ignore[arg-type]
            approval_service=self.approval_service,
            rab_repo=self.rab_repo,
        )
        self.steps: list[dict] = []

    def _log(self, step: str, detail: str) -> None:
        logger.info("[DEMO_LAB] %s: %s", step, detail)
        self.steps.append({"step": step, "detail": detail})

    async def _ensure_real_issue(self) -> None:
        """Create one fresh live Jira issue for this Demo Lab run."""
        client = getattr(self.orchestrator, "jira_client", None)
        if not client or not hasattr(client, "create_issue"):
            return
        try:
            from app.config import get_settings
            settings = get_settings()
            project = getattr(self, "_real_project", None) or settings.JIRA_PROJECT_KEY or "TEST"
            # Build RAB block for advisory validation
            from datetime import datetime, timezone
            rab_block = (
                f"RAB Details (demo lab real ticket):\n"
                f"- Date/Time: {datetime.now(timezone.utc).isoformat()}\n"
                f"- RAB Approver: {self.creator_name}\n"
                f"- PR Link: https://github.com/example/repo/pull/42\n"
                f"- Pipeline Link: https://dev.azure.com/example/pipeline/99\n"
                f"- Developer: {self.creator_name}\n"
                f"- Team Lead: {self.creator_name}\n"
                f"- PM: {self.creator_name}\n"
                f"- QA: {self.creator_name}\n"
                f"- Environment: staging\n"
                f"- Rollback/Mitigation: revert\n"
                f"Attachments: blast radius image attached (simulated)\n"
            )
            description = f"{self.summary}\n\n{rab_block}"
            custom_fields = {}
            field_values = {
                "DATE_TIME": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+0000"),
                "RAB_APPROVER": self.creator_name,
                "PR_LINK": "https://github.com/example/repo/pull/42",
                "PIPELINE_LINK": "https://dev.azure.com/example/pipeline/99",
                "DEVELOPER": self.creator_name,
                "TEAM_LEAD": self.creator_name,
                "PM": self.creator_name,
                "QA": self.creator_name,
                "ENVIRONMENT": "staging",
                "ROLLBACK_DETAILS": "revert",
                "DEPLOYMENT_INSTRUCTIONS": "Deploy through the release pipeline.",
                "OUTCOME_NOTES": "Demo Lab live-ticket scenario.",
                "ROLLBACK_STRATEGY": "Revert the deployment.",
                "MITIGATION_STRATEGY": "Pause rollout and notify the team.",
                "RELATED_RELEASE_REFERENCE": "DEMO-LAB",
                "RELEASE_OUTCOME": "Pending scenario outcome",
                "ENVIRONMENTS": "staging",
                "DEVELOPMENT": self.creator_name,
            }
            for name, value in field_values.items():
                field_id = getattr(settings, f"JIRA_FIELD_{name}", "")
                if field_id:
                    # Jira paragraph/rich-text custom fields require ADF;
                    # plain text fields (links, names, dates) remain strings.
                    if name in {
                        "ROLLBACK_DETAILS", "DEPLOYMENT_INSTRUCTIONS", "OUTCOME_NOTES",
                        "ROLLBACK_STRATEGY", "MITIGATION_STRATEGY",
                    }:
                        custom_fields[field_id] = {
                            "type": "doc",
                            "version": 1,
                            "content": [{
                                "type": "paragraph",
                                "content": [{"type": "text", "text": value}],
                            }],
                        }
                    else:
                        custom_fields[field_id] = value
            # Create with Jira's portable core fields. Priority and assignee are
            # project-specific and frequently cause create failures; the
            # workflow can enrich the issue after creation when configured.
            result = await client.create_issue(
                project, self.summary, description,
                issuetype="Task", labels=["demo", "rab-auto", "live-demo"], custom_fields=custom_fields,
            )
            real_key = result.get("key")
            if not real_key or not re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", str(real_key)):
                raise RuntimeError(f"Jira creation returned no valid issue key: {result}")
            logger.info("Demo Lab real Jira issue created: %s (project %s)", real_key, project)
            self.issue_key = real_key
            # Assign the live Jira issue to its creator/current API user. This
            # keeps Assignee a real Jira field and makes the full-spec audit
            # match what was actually created, rather than inferring it locally.
            try:
                myself = await client._get("/rest/api/3/myself")
                account_id = myself.get("accountId") if isinstance(myself, dict) else None
                if account_id:
                    await client.update_issue(real_key, {"assignee": {"accountId": account_id}})
            except Exception as exc:
                logger.warning("Could not assign Demo Lab issue %s to its creator: %s", real_key, exc)
            # Verify and persist the exact Jira payload before any local
            # workflow state is allowed to start.
            await hydrate_issue(real_key, client=client, repo=self.rab_repo)
        except Exception:
            logger.exception("Demo Lab Jira ticket creation failed for %s", self.issue_key)
            raise

    async def _reset_issue(self) -> None:
        """Clear any prior state for this key so the demo can be re-run."""
        # For real Jira, don't delete the Jira issue itself, just clear local audit state so rerun is clean
        self.approval_service.reset_issue(self.issue_key)
        await self.rab_repo.delete_record(self.issue_key)

    @staticmethod
    async def cleanup_demo_issues(project: str | None = None, max_delete: int = 50) -> dict:
        """Delete live-demo Jira tickets created by the Demo Lab (label `live-demo`).

        Demo runs create one Jira issue per run and never clean up; call this
        from Tools to bound live-project spam. Returns {"deleted": [...], "failed": [...]}.
        """
        from app.config import get_settings

        settings = get_settings()
        project = project or settings.JIRA_PROJECT_KEY or "TEST"
        client = JiraClient()
        if not client.base_url or not client.email or not client.api_token:
            raise RuntimeError("Jira credentials are not configured")
        data = await client.search_issues(
            f'project = "{project}" AND labels = live-demo ORDER BY updated DESC',
            max_results=min(max_delete, 50),
        )
        deleted: list[str] = []
        failed: list[str] = []
        for it in data.get("issues", [])[:max_delete]:
            key = it.get("key")
            if not key:
                continue
            try:
                await client.delete_issue(key)
                deleted.append(key)
            except Exception as e:
                logger.warning("Demo cleanup failed for %s: %s", key, e)
                failed.append(f"{key}: {e}")
        logger.info("Demo cleanup project=%s deleted=%d failed=%d", project, len(deleted), len(failed))
        return {"deleted": deleted, "failed": failed}

    async def run_full_approval(self, needs_meeting: bool = False) -> DummyFlowResult:
        """Validation → SDL approve → SDM approve → meeting decision."""
        logger.info("Starting dummy RAB flow for %s", self.issue_key)
        await self._ensure_real_issue()
        await self._reset_issue()

        validation = await self.orchestrator.handle_jira_event(
            issue_key=self.issue_key,
            event_type="jira:issue_created",
        )
        self._log("validation", validation)

        sdl = await self.orchestrator.handle_approval_callback(
            self.issue_key, "approve", approver=self.creator_name, reason="Looks good"
        )
        self._log("sdl_approval", sdl.get("detail", ""))

        sdm = await self.orchestrator.handle_approval_callback(
            self.issue_key, "approve", approver=self.creator_name, reason="Ship it"
        )
        self._log("sdm_approval", sdm.get("detail", ""))

        meeting = await self.orchestrator.handle_meeting_callback(self.issue_key, needs_meeting)
        self._log("meeting_decision", meeting)

        logger.info("Dummy RAB flow completed for %s", self.issue_key)
        return DummyFlowResult(issue_key=self.issue_key, steps=self.steps, status="ok")

    async def run_rejection(self) -> DummyFlowResult:
        """Validation → SDL reject → flow stops."""
        logger.info("Starting dummy RAB rejection flow for %s", self.issue_key)
        await self._ensure_real_issue()
        await self._reset_issue()

        validation = await self.orchestrator.handle_jira_event(
            issue_key=self.issue_key,
            event_type="jira:issue_created",
        )
        self._log("validation", validation)

        rejected = await self.orchestrator.handle_approval_callback(
            self.issue_key, "reject", approver=self.creator_name, reason="Missing rollout plan"
        )
        self._log("sdl_rejection", rejected.get("detail", ""))

        logger.info("Dummy RAB rejection flow completed for %s", self.issue_key)
        return DummyFlowResult(issue_key=self.issue_key, steps=self.steps, status="rejected")

    async def run_pending_sdl(self) -> DummyFlowResult:
        """Validation → SDL requested (pending approval at SDL)."""
        logger.info("Starting pending-SDL flow for %s", self.issue_key)
        await self._ensure_real_issue()
        await self._reset_issue()
        validation = await self.orchestrator.handle_jira_event(
            issue_key=self.issue_key, event_type="jira:issue_created",
        )
        self._log("validation", validation)
        self._log("sdl_pending", "SDL approval requested — awaiting SDL decision")
        return DummyFlowResult(issue_key=self.issue_key, steps=self.steps, status="pending_sdl")

    async def run_pending_sdm(self) -> DummyFlowResult:
        """Validation → SDL approve → SDM requested (pending at SDM)."""
        logger.info("Starting pending-SDM flow for %s", self.issue_key)
        await self._ensure_real_issue()
        await self._reset_issue()
        validation = await self.orchestrator.handle_jira_event(
            issue_key=self.issue_key, event_type="jira:issue_created",
        )
        self._log("validation", validation)
        sdl = await self.orchestrator.handle_approval_callback(
            self.issue_key, "approve", approver=self.creator_name, reason="Looks good"
        )
        self._log("sdl_approval", sdl.get("detail", ""))
        self._log("sdm_pending", "SDM approval requested — awaiting SDM decision")
        return DummyFlowResult(issue_key=self.issue_key, steps=self.steps, status="pending_sdm")

    async def run_validation_failed(self) -> DummyFlowResult:
        """Directly create a validation_failed record (simulates missing fields) — uses strict mode to force hard-fail."""
        logger.info("Starting validation-failed flow for %s", self.issue_key)
        await self._ensure_real_issue()
        await self._reset_issue()

        class FailingValidator:
            def validate(self, issue_data: dict):
                return type("V", (), {
                    "valid": False,
                    "detail": "Missing required fields: RAB Approver, PR Link, QA",
                    "missing_fields": ["RAB Approver", "PR Link", "QA"],
                })()
            def extract_field_value(self, *a, **kw): return None

        # Per-instance strict override — no os.environ mutation, so concurrent
        # requests are unaffected (previous implementation leaked strict mode globally).
        orch = RabOrchestrator(
            jira_client=self.jira_client,
            approval_service=self.approval_service,
            rab_repo=self.rab_repo,
            field_validator=FailingValidator(),
            strict_validation=True,
        )
        result = await orch.handle_jira_event(self.issue_key, "jira:issue_created")
        self._log("validation", result)
        return DummyFlowResult(issue_key=self.issue_key, steps=self.steps, status="validation_failed")

    async def run_validated_with_notes(self) -> DummyFlowResult:
        """Advisory validated_with_notes — GET and NOTE missing fields per drawio, workflow continues."""
        logger.info("Starting validated_with_notes flow for %s", self.issue_key)
        await self._ensure_real_issue()
        await self._reset_issue()

        orch = RabOrchestrator(
            jira_client=self.jira_client,
            approval_service=self.approval_service,
            rab_repo=self.rab_repo,
            field_validator=_DemoPartialValidator(),
        )
        result = await orch.handle_jira_event(self.issue_key, "jira:issue_created")
        self._log("validation", result)
        # Verify it was stored as validated_with_notes
        rec = await self.rab_repo.get_record(self.issue_key)
        status = rec["status"] if rec else "unknown"
        self._log("validated_with_notes", f"status={status} — {result}")
        return DummyFlowResult(issue_key=self.issue_key, steps=self.steps, status="validated_with_notes")

    async def run_sdm_rejection(self) -> DummyFlowResult:
        """Validation → SDL approve → SDM reject."""
        logger.info("Starting SDM rejection flow for %s", self.issue_key)
        await self._ensure_real_issue()
        await self._reset_issue()
        await self.orchestrator.handle_jira_event(self.issue_key, "jira:issue_created")
        self._log("validation", "approval_requested_sdl")
        await self.orchestrator.handle_approval_callback(self.issue_key, "approve", approver=self.creator_name, reason="Looks good")
        self._log("sdl_approval", "SDL approved — SDM approval requested")
        rejected = await self.orchestrator.handle_approval_callback(self.issue_key, "reject", approver=self.creator_name, reason="Risk too high")
        self._log("sdm_rejection", rejected.get("detail", ""))
        return DummyFlowResult(issue_key=self.issue_key, steps=self.steps, status="rejected")

    async def run_aging_pending(self, days: int = 3) -> DummyFlowResult:
        """Create a pending SDL record aged by `days` so it appears in 'Waiting for Approval'."""
        await self.run_pending_sdl()
        # Backdate updated_at so get_aging_records picks it up
        from datetime import datetime, timedelta, timezone
        from app.database import get_db
        aged = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        db = await get_db()
        await db.execute("UPDATE rab_records SET updated_at = ? WHERE issue_key = ?", (aged, self.issue_key))
        await db.commit()
        self._log("aging", f"Backdated to {days} days ago for waiting list")
        return DummyFlowResult(issue_key=self.issue_key, steps=self.steps, status="pending_sdl")

