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
        return {
            "key": self.issue_key,
            "fields": {
                "summary": self.summary,
                "assignee": {"displayName": "Demo Dev"},
                "reporter": {"displayName": "Demo PM"},
            },
        }

    async def add_comment(self, issue_key: str, body: str) -> dict:
        first_line = body.splitlines()[0] if body else ""
        logger.info("[DUMMY] Jira comment on %s: %s", issue_key, first_line)
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


class DummyFlowService:
    """Runs the full SDL → SDM → meeting RAB workflow against stub services."""

    def __init__(self, issue_key: str = "DEMO-1", summary: str = "Demo release ticket") -> None:
        self.issue_key = issue_key
        self.summary = summary
        self.approval_service = ApprovalService()
        self.rab_repo = RabRepository()
        self.orchestrator = RabOrchestrator(
            jira_client=StubJiraClient(issue_key, summary),
            field_validator=_DemoPassValidator(),
            approval_service=self.approval_service,
            rab_repo=self.rab_repo,
        )
        self.steps: list[dict] = []

    def _log(self, step: str, detail: str) -> None:
        logger.info("[DUMMY] %s: %s", step, detail)
        self.steps.append({"step": step, "detail": detail})

    async def _reset_issue(self) -> None:
        """Clear any prior state for this key so the demo can be re-run."""
        self.approval_service.reset_issue(self.issue_key)
        await self.rab_repo.delete_record(self.issue_key)

    async def run_full_approval(self, needs_meeting: bool = False) -> DummyFlowResult:
        """Validation → SDL approve → SDM approve → meeting decision."""
        logger.info("Starting dummy RAB flow for %s", self.issue_key)
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
        """Directly create a validation_failed record (simulates missing fields)."""
        logger.info("Starting validation-failed flow for %s", self.issue_key)
        await self._reset_issue()

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
    async def seed_demo_dataset() -> list["DummyFlowResult"]:
        """Create a full demo dataset covering every pipeline KPI bucket."""
        specs = [
            ("DEMO-PENDING-SDL", "Pending at SDL — needs SDL review", "pending_sdl", {}),
            ("DEMO-PENDING-SDM", "Pending at SDM — SDL approved", "pending_sdm", {}),
            ("DEMO-FAILED-1", "Validation failed — missing fields", "validation_failed", {}),
            ("DEMO-REJECT-SDL", "Rejected by SDL", "rejected_sdl", {}),
            ("DEMO-REJECT-SDM", "Rejected by SDM", "rejected_sdm", {}),
            ("DEMO-READY-1", "Release ready — no meeting", "full", {"needs_meeting": False}),
            ("DEMO-MEETING-1", "Meeting scheduled", "full", {"needs_meeting": True}),
            ("DEMO-AGING-1", "Aging — pending 3 days", "aging", {"days": 3}),
        ]
        results: list[DummyFlowResult] = []
        for key, summary, scenario, kwargs in specs:
            svc = DummyFlowService(issue_key=key, summary=summary)
            if scenario == "pending_sdl":
                r = await svc.run_pending_sdl()
            elif scenario == "pending_sdm":
                r = await svc.run_pending_sdm()
            elif scenario == "validation_failed":
                r = await svc.run_validation_failed()
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
