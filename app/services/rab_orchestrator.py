"""RAB Orchestrator – processes Jira events through the full RAB workflow (monitor mode)."""

import asyncio
import logging
import uuid

from app.repositories.rab_repository import RabRepository
from app.services.approval_service import ApprovalService, ApprovalStep
from app.services.field_validator import FieldValidator
from app.services.jira_client import JiraClient, JiraClientError
from app.services.status_codes import FLOW_STATUSES, RabStatus

logger = logging.getLogger(__name__)

_START_EVENT_TYPES = {"jira:issue_created", "jira:issue_updated"}

_issue_locks: dict[str, asyncio.Lock] = {}
_issue_locks_lock = asyncio.Lock()
_MAX_ISSUE_LOCKS = 1024


async def _get_issue_lock(issue_key: str) -> asyncio.Lock:
    async with _issue_locks_lock:
        lock = _issue_locks.get(issue_key)
        if lock is None:
            if len(_issue_locks) >= _MAX_ISSUE_LOCKS:
                for existing_key in list(_issue_locks):
                    if not _issue_locks[existing_key].locked():
                        del _issue_locks[existing_key]
                        break
            lock = asyncio.Lock()
            _issue_locks[issue_key] = lock
        return lock


class RabOrchestrator:
    def __init__(
        self,
        jira_client: JiraClient | None = None,
        field_validator: FieldValidator | None = None,
        teams_client=None,
        approval_service: ApprovalService | None = None,
        rab_repo: RabRepository | None = None,
    ) -> None:
        # teams_client kept for backward compat but ignored — monitor mode, approvals in Jira
        self.jira_client = jira_client or JiraClient()
        self.field_validator = field_validator or FieldValidator()
        self.teams_client = teams_client
        self.approval_service = approval_service or ApprovalService()
        self.rab_repo = rab_repo or RabRepository()

    async def handle_jira_event(
        self,
        issue_key: str,
        event_type: str | None,
    ) -> str:
        logger.info("Orchestrator received event: issue_key=%s, event_type=%s", issue_key, event_type)

        if event_type is not None and event_type not in _START_EVENT_TYPES:
            logger.info("Event %s is not a workflow-starting event for %s — monitoring only", event_type, issue_key)
            lock = await _get_issue_lock(issue_key)
            async with lock:
                issue_data = await self._fetch_issue(issue_key)
                if issue_data:
                    validation = self.field_validator.validate(issue_data)
                    summary = issue_data.get("fields", {}).get("summary", "") or ""
                    await self.rab_repo.upsert_record(issue_key, {
                        "summary": summary,
                        "validation_result": validation.detail if not validation.valid else "",
                        "status": "validated" if validation.valid else "validation_failed",
                    })
                    existing = await self.rab_repo.get_record(issue_key)
                    if existing and existing.get("status") in FLOW_STATUSES:
                        await self.rab_repo.upsert_record(issue_key, {"status": existing["status"]})
            return "monitored"

        lock = await _get_issue_lock(issue_key)
        async with lock:
            existing = self.approval_service.get_approval(issue_key)
            if existing is not None:
                # Approval already exists in the service store — workflow already started
                logger.info("Workflow already started for %s — ignoring start event %s", issue_key, event_type)
                return "already_in_progress"
            # No approval in store — check the raw DB record
            record = await self.rab_repo.get_record(issue_key)
            if record and (
                record.get("sdl_approval") in ("requested", "approved", "rejected")
                or record.get("sdm_approval") in ("requested", "approved", "rejected")
            ):
                # DB record indicates an approval was previously started
                logger.info("Workflow already started for %s — ignoring start event %s", issue_key, event_type)
                # Hydrate the approval state from the DB record so subsequent logic works
                existing = self.approval_service.load_from_record(record)
                return "already_in_progress"
            # No prior state — proceed with new workflow

            issue_data = await self._fetch_issue(issue_key)
            if not issue_data:
                return "error_fetching_issue_data"

            validation = self.field_validator.validate(issue_data)
            fields = issue_data.get("fields", {})
            creator_data = fields.get("creator") or fields.get("reporter") or {}
            assignee_data = fields.get("assignee") or {}
            await self.rab_repo.upsert_record(issue_key, {
                "creator": creator_data.get("displayName") or creator_data.get("accountId") or "",
                "assignee": assignee_data.get("displayName") or assignee_data.get("accountId") or "",
            })
            await self.rab_repo.record_validation(issue_key, validation.valid, validation.detail)
            if not validation.valid:
                msg = f"Validation failed.\n\n{validation.detail}\n\nPlease update the ticket and trigger re-check."
                await self._add_comment(issue_key, f"RAB Automation: {msg}")
                await self._send_card("Validation Failed")
                return f"validation_failed: {validation.detail}"

            await self._add_comment(issue_key, "RAB Automation: Ticket validation passed — starting approvals.")
            await self._send_card("Validation Passed")

            summary = issue_data.get("fields", {}).get("summary", "No summary")
            self.approval_service.create_approval(issue_key, summary)

            await self._request_approval(issue_key, summary, ApprovalStep.SDL)
            return "approval_requested_sdl"

    async def _fetch_issue(self, issue_key: str) -> dict | None:
        try:
            return await self.jira_client.get_issue(issue_key)
        except JiraClientError as e:
            logger.error("Failed to fetch issue %s: %s", issue_key, e)
            return None

    async def _add_comment(self, issue_key: str, body: str) -> None:
        try:
            await self.jira_client.add_comment(issue_key, body)
        except JiraClientError as e:
            logger.error("Failed to add comment for %s: %s", issue_key, e)

    async def _send_card(self, title: str, card: dict | None = None) -> None:
        # Monitor mode — no Teams delivery; log for audit trail
        logger.info("Monitor event: %s", title)

    async def _request_approval(self, issue_key: str, summary: str, step: ApprovalStep) -> None:
        approval_id = str(uuid.uuid4())
        self.approval_service.record_approval_id(issue_key, approval_id)
        column = f"{step.value.lower()}_approval"
        if step == ApprovalStep.SDL:
            status_val = RabStatus.SDL_REQUESTED.value
        else:
            status_val = RabStatus.SDM_REQUESTED.value
        await self.rab_repo.upsert_record(issue_key, {
            column: "requested",
            f"{column}_id": approval_id,
            "status": status_val,
        })
        await self._add_comment(issue_key, f"RAB Automation: {step.value} approval requested.")
        await self._send_card(f"{step.value} Approval: {issue_key}")

    async def handle_approval_callback(
        self,
        issue_key: str,
        action: str,
        approver: str = "",
        reason: str | None = None,
        approval_id: str = "",
    ) -> dict:
        lock = await _get_issue_lock(issue_key)
        async with lock:
            state = self.approval_service.get_approval(issue_key)
            if not state:
                record = await self.rab_repo.get_record(issue_key)
                state = self.approval_service.load_from_record(record) if record else None
                if not state:
                    return {"status": "error", "detail": "No active approval"}

            step = "SDL" if state.current_step == ApprovalStep.SDL else "SDM"
            recorded = state.sdl_approval_id if step == "SDL" else state.sdm_approval_id
            if approval_id and recorded and approval_id != recorded:
                logger.warning(
                    "Rejected callback for %s: approval_id %s does not match recorded %s id %s",
                    issue_key, approval_id, step, recorded,
                )
                return {"status": "error", "detail": f"Invalid approval reference for {step} step"}

            result = self.approval_service.process_response(issue_key, action, reason)
            decision = result.get("decision")

            if result.get("error") and decision is None:
                logger.warning("Approval callback rejected for %s: %s", issue_key, result["error"])
                return {"status": "error", "detail": result["error"]}

            await self.rab_repo.record_approval_event(issue_key, step, action, approver, reason or "")

            if decision == "rejected":
                rejected_by = result["rejected_by"]
                await self._add_comment(
                    issue_key,
                    f"RAB Automation: {rejected_by} rejected.\nReason: {reason or 'No reason provided.'}",
                )
                await self._send_card(f"Rejected: {issue_key}")
                return {"status": "rejected", "rejected_by": rejected_by, "detail": f"Rejected by {rejected_by}"}

            if decision == "approved":
                await self._add_comment(issue_key, f"RAB Automation: {step} approved.")
                await self._send_card(f"Approved by {step}: {issue_key}")

                next_step = result.get("next_step")
                if next_step == ApprovalStep.SDM.value:
                    await self._request_approval(issue_key, state.summary, ApprovalStep.SDM)
                    return {"status": "approved", "detail": "SDL approved — SDM approval requested", "next": "sdm"}
                else:
                    await self._add_comment(issue_key, "RAB Automation: All approvals complete. Requesting meeting decision.")
                    await self._request_meeting_decision(issue_key)
                    return {"status": "approved", "detail": "All approvals complete", "next": "meeting_decision"}

            return {"status": "error", "detail": result.get("error", "Unknown")}

    async def _request_meeting_decision(self, issue_key: str) -> None:
        await self._send_card(f"Meeting Decision: {issue_key}")
        await self._add_comment(issue_key, "RAB Automation: Meeting decision requested.")

    async def handle_meeting_callback(self, issue_key: str, needs_meeting: bool) -> str:
        lock = await _get_issue_lock(issue_key)
        async with lock:
            await self.rab_repo.upsert_record(issue_key, {
                "meeting_needed": 1 if needs_meeting else 0,
                "status": RabStatus.MEETING_SCHEDULED.value if needs_meeting else RabStatus.RELEASE_READY.value,
            })
            if needs_meeting:
                await self._add_comment(issue_key, "RAB Automation: Meeting will be scheduled. Resolving attendees from ticket.")
                await self._send_card("Meeting Needed")
                return "meeting_scheduled"
            else:
                await self._add_comment(issue_key, "RAB Automation: No meeting needed — release ticket finalized.")
                await self._send_card("Release Ready")
                return "release_ready"
