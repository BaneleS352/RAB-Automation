"""Simulated RAB approval flow for demos — produces real logs and audit records.

Reuses the real RabOrchestrator but replaces the Jira client with a stub so
the full lifecycle runs without any external network calls. Every stage is
logged at INFO and persisted through RabRepository just like a real ticket.
"""

import logging
from dataclasses import dataclass, field

from app.repositories.rab_repository import RabRepository
from app.services.approval_service import ApprovalService
from app.services.rab_orchestrator import RabOrchestrator

logger = logging.getLogger(__name__)


class StubJiraClient:
    """In-memory Jira client that always returns valid issue data."""

    def __init__(self, issue_key: str, summary: str) -> None:
        self.issue_key = issue_key
        self.summary = summary

    async def get_issue(self, issue_key: str) -> dict:
        logger.info("[DUMMY] Fetching issue %s from stub Jira", issue_key)
        # Return rich fields so dashboard no longer shows blank details for dummy tickets (same fix as real Jira sync)
        return {
            "key": self.issue_key,
            "fields": {
                "summary": self.summary,
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": f"{self.summary} — demo ticket with rich details (priority High, labels demo)"}]}],
                },
                "assignee": {"displayName": "Demo Dev"},
                "reporter": {"displayName": "Demo PM"},
                "creator": {"displayName": "Demo Creator"},
                "priority": {"name": "High"},
                "issuetype": {"name": "Task"},
                "status": {"name": "Open"},
                "labels": ["demo", "rab-auto"],
                "updated": "2026-08-28T11:45:00.000+0000",
            },
        }

    async def add_comment(self, issue_key: str, body: str) -> dict:
        first_line = body.splitlines()[0] if body else ""
        logger.info("[DUMMY] Jira comment on %s: %s", issue_key, first_line)
        return {}

    async def transition_issue(self, issue_key: str, transition_id: str) -> dict:
        logger.info("[DUMMY] Jira transition on %s: id=%s (no-op stub)", issue_key, transition_id)
        return {}


@dataclass
class DummyFlowResult:
    issue_key: str
    steps: list[dict] = field(default_factory=list)
    status: str = "ok"


class _DemoPassValidator:
    """Validator that always passes for demo — avoids fail-closed on missing JIRA_FIELD_* mappings."""
    def validate(self, issue_data: dict):
        return type("V", (), {"valid": True, "detail": "All required fields are present.", "missing_fields": []})()
    def extract_field_value(self, *a, **kw): return "demo"


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
    """Runs the full SDL → SDM → meeting RAB workflow against stub services.
    Now also supports real Jira tickets when use_real_jira=True (per demo lab switch).
    """

    def __init__(self, issue_key: str = "DEMO-1", summary: str = "Demo release ticket", use_real_jira: bool = False) -> None:
        self.issue_key = issue_key
        self.summary = summary
        self.use_real_jira = use_real_jira
        self.approval_service = ApprovalService()
        self.rab_repo = RabRepository()
        # Switch from stub to real Jira when requested and configured
        if use_real_jira:
            from app.services.jira_client import JiraClient
            from app.services.field_validator import FieldValidator
            from app.config import get_settings

            settings = get_settings()
            jira_client = JiraClient()
            # If Jira not configured, fall back to stub and warn
            if not jira_client.base_url or not jira_client.email or not jira_client.api_token:
                logger.warning("Demo Lab real Jira requested but Jira not configured — falling back to stub for %s", issue_key)
                jira_client = StubJiraClient(issue_key, summary)
                validator = _DemoPassValidator()
                self._real_project = None
            else:
                # Real tickets use the real advisory validator (GET and NOTE per drawio) so missing fields are noted, not stubbed
                validator = FieldValidator()
                self._real_project = settings.JIRA_PROJECT_KEY or "TEST"
        else:
            jira_client = StubJiraClient(issue_key, summary)
            validator = _DemoPassValidator()
            self._real_project = None

        self.orchestrator = RabOrchestrator(
            jira_client=jira_client,
            field_validator=validator,
            approval_service=self.approval_service,
            rab_repo=self.rab_repo,
        )
        self.steps: list[dict] = []

    def _log(self, step: str, detail: str) -> None:
        logger.info("[DUMMY] %s: %s", step, detail)
        self.steps.append({"step": step, "detail": detail})

    async def _ensure_real_issue(self) -> None:
        """When use_real_jira=True, create a real Jira issue and switch self.issue_key to it."""
        if not getattr(self, "use_real_jira", False):
            return
        # Check if jira_client is real (has create_issue and is configured)
        client = getattr(self.orchestrator, "jira_client", None)
        if not client or not hasattr(client, "create_issue"):
            return
        # If already a real key (e.g., TEST-123) we already created, don’t recreate each step
        if self.issue_key and "-" in self.issue_key and not self.issue_key.startswith("DEMO-"):
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
                f"- RAB Approver: sdl@example.com\n"
                f"- PR Link: https://github.com/example/repo/pull/42\n"
                f"- Pipeline Link: https://dev.azure.com/example/pipeline/99\n"
                f"- Developer: dev@example.com\n"
                f"- Team Lead: lead@example.com\n"
                f"- PM: pm@example.com\n"
                f"- QA: qa@example.com\n"
                f"- Environment: staging\n"
                f"- Rollback/Mitigation: revert\n"
                f"Attachments: blast radius image attached (simulated)\n"
            )
            description = f"{self.summary}\n\n{rab_block}"
            # Try to get assignee accountId from a quick myself call
            assignee_id = None
            try:
                import httpx
                base = settings.JIRA_BASE_URL
                if base:
                    async with httpx.AsyncClient(timeout=10) as c:
                        r = await c.get(f"{base.rstrip('/')}/rest/api/3/myself", auth=httpx.BasicAuth(settings.JIRA_EMAIL or "", settings.JIRA_API_TOKEN or ""), headers={"Accept":"application/json"})
                        if r.status_code == 200:
                            assignee_id = r.json().get("accountId")
            except Exception:
                pass
            result = await client.create_issue(project, self.summary, description, issuetype="Task", labels=["demo", "rab-auto", "real"], priority="Medium", assignee_account_id=assignee_id)
            real_key = result.get("key") or result.get("id")
            if real_key and real_key != self.issue_key:
                logger.info("Demo Lab real Jira issue created: %s -> %s (project %s)", self.issue_key, real_key, project)
                # Switch to real key for this run
                self.issue_key = real_key
                # Also update the orchestrator's stub client if it was swapped? The orchestrator already has real client, so fetch will work
        except Exception as e:
            logger.warning("Demo Lab real Jira creation failed for %s: %s — falling back to stub", self.issue_key, e)

    async def _reset_issue(self) -> None:
        """Clear any prior state for this key so the demo can be re-run."""
        # For real Jira, don't delete the Jira issue itself, just clear local audit state so rerun is clean
        self.approval_service.reset_issue(self.issue_key)
        await self.rab_repo.delete_record(self.issue_key)

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
            self.issue_key, "approve", approver="Demo SDL", reason="Looks good"
        )
        self._log("sdl_approval", sdl.get("detail", ""))

        sdm = await self.orchestrator.handle_approval_callback(
            self.issue_key, "approve", approver="Demo SDM", reason="Ship it"
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
            self.issue_key, "reject", approver="Demo SDL", reason="Missing rollout plan"
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
            self.issue_key, "approve", approver="Demo SDL", reason="Looks good"
        )
        self._log("sdl_approval", sdl.get("detail", ""))
        self._log("sdm_pending", "SDM approval requested — awaiting SDM decision")
        return DummyFlowResult(issue_key=self.issue_key, steps=self.steps, status="pending_sdm")

    async def run_validation_failed(self) -> DummyFlowResult:
        """Directly create a validation_failed record (simulates missing fields) — uses strict mode to force hard-fail."""
        logger.info("Starting validation-failed flow for %s", self.issue_key)
        await self._ensure_real_issue()
        await self._reset_issue()

        import os
        prev = os.environ.get("RAB_STRICT_VALIDATION")
        os.environ["RAB_STRICT_VALIDATION"] = "true"
        try:
            class FailingValidator:
                def validate(self, issue_data: dict):
                    return type("V", (), {
                        "valid": False,
                        "detail": "Missing required fields: RAB Approver, PR Link, QA",
                        "missing_fields": ["RAB Approver", "PR Link", "QA"],
                    })()
                def extract_field_value(self, *a, **kw): return None

            orch = RabOrchestrator(
                jira_client=StubJiraClient(self.issue_key, self.summary),
                approval_service=self.approval_service,
                rab_repo=self.rab_repo,
                field_validator=FailingValidator(),
            )
            result = await orch.handle_jira_event(self.issue_key, "jira:issue_created")
            self._log("validation", result)
            return DummyFlowResult(issue_key=self.issue_key, steps=self.steps, status="validation_failed")
        finally:
            if prev is None:
                os.environ.pop("RAB_STRICT_VALIDATION", None)
            else:
                os.environ["RAB_STRICT_VALIDATION"] = prev

    async def run_validated_with_notes(self) -> DummyFlowResult:
        """Advisory validated_with_notes — GET and NOTE missing fields per drawio, workflow continues."""
        logger.info("Starting validated_with_notes flow for %s", self.issue_key)
        await self._ensure_real_issue()
        await self._reset_issue()

        # Use partial validator + stub that only has 4/12 fields (RAB, PR Link, Pipeline Link, Team Lead) — matches Power Automate check
        class PartialStubJiraClient(StubJiraClient):
            async def get_issue(self, issue_key: str) -> dict:
                base = await super().get_issue(issue_key)
                # Override to only have 4 RAB fields present in description
                base["fields"]["description"] = {
                    "type": "doc",
                    "version": 1,
                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "RAB Approver: sdl@example.com\nPR Link: https://example.com/pr\nPipeline Link: https://example.com/pipe\nTeam Lead: lead@example.com\nEnvironment: staging"}]}],
                }
                return base

        orch = RabOrchestrator(
            jira_client=PartialStubJiraClient(self.issue_key, self.summary),
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
        await self._reset_issue()
        await self.orchestrator.handle_jira_event(self.issue_key, "jira:issue_created")
        self._log("validation", "approval_requested_sdl")
        await self.orchestrator.handle_approval_callback(self.issue_key, "approve", approver="Demo SDL", reason="Looks good")
        self._log("sdl_approval", "SDL approved — SDM approval requested")
        rejected = await self.orchestrator.handle_approval_callback(self.issue_key, "reject", approver="Demo SDM", reason="Risk too high")
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

    @staticmethod
    async def seed_demo_dataset(use_real_jira: bool = False) -> list["DummyFlowResult"]:
        """Create a full demo dataset covering every pipeline KPI bucket — updated for advisory GET-and-NOTE.
        When use_real_jira=True and Jira is configured, creates real Jira issues (TEST project) instead of stub DEMO- keys.
        """
        specs = [
            ("DEMO-PENDING-SDL", "Pending at SDL — needs SDL review", "pending_sdl", {}),
            ("DEMO-PENDING-SDM", "Pending at SDM — SDL approved", "pending_sdm", {}),
            ("DEMO-FAILED-1", "Validation failed — missing fields (strict)", "validation_failed", {}),
            ("DEMO-NOTED-1", "Validated with notes — 8/12 missing (advisory, per drawio)", "validated_with_notes", {}),
            ("DEMO-REJECT-SDL", "Rejected by SDL", "rejected_sdl", {}),
            ("DEMO-REJECT-SDM", "Rejected by SDM", "rejected_sdm", {}),
            ("DEMO-READY-1", "Release ready — no meeting", "full", {"needs_meeting": False}),
            ("DEMO-MEETING-1", "Meeting scheduled", "full", {"needs_meeting": True}),
            ("DEMO-AGING-1", "Aging — pending 3 days", "aging", {"days": 3}),
        ]
        results: list[DummyFlowResult] = []
        for key, summary, scenario, kwargs in specs:
            svc = DummyFlowService(issue_key=key, summary=summary, use_real_jira=use_real_jira)
            if scenario == "pending_sdl":
                r = await svc.run_pending_sdl()
            elif scenario == "pending_sdm":
                r = await svc.run_pending_sdm()
            elif scenario == "validation_failed":
                r = await svc.run_validation_failed()
            elif scenario == "validated_with_notes":
                r = await svc.run_validated_with_notes()
            elif scenario == "rejected_sdl":
                r = await svc.run_rejection()
            elif scenario == "rejected_sdm":
                r = await svc.run_sdm_rejection()
            elif scenario == "full":
                r = await svc.run_full_approval(**kwargs)
            elif scenario == "aging":
                r = await svc.run_aging_pending(**kwargs)
            else:
                r = await svc.run_full_approval()
            results.append(r)
        return results
