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


class DummyFlowService:
    """Runs the full SDL → SDM → meeting RAB workflow against stub services."""

    def __init__(self, issue_key: str = "DEMO-1", summary: str = "Demo release ticket") -> None:
        self.issue_key = issue_key
        self.summary = summary
        self.approval_service = ApprovalService()
        self.rab_repo = RabRepository()
        self.orchestrator = RabOrchestrator(
            jira_client=StubJiraClient(issue_key, summary),
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
