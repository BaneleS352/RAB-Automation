"""RAB Orchestrator – processes Jira events through the full RAB workflow."""

import logging
import uuid

from app.repositories.rab_repository import RabRepository
from app.services.approval_service import ApprovalService, ApprovalStep
from app.services.azure_devops_client import AzureDevOpsClient, AzureDevOpsClientError
from app.services.card_templates import (
    approval_request_card,
    developer_notification_card,
    meeting_decision_card,
    rejection_notification_card,
    validation_failed_card,
    validation_passed_card,
)
from app.services.field_validator import FieldValidator
from app.services.jira_client import JiraClient, JiraClientError
from app.services.teams_client import TeamsClient, TeamsClientError, get_conversation

logger = logging.getLogger(__name__)


class RabOrchestrator:
    def __init__(self) -> None:
        self.jira_client = JiraClient()
        self.field_validator = FieldValidator()
        self.azure_client = AzureDevOpsClient()
        self.teams_client = TeamsClient()
        self.approval_service = ApprovalService()
        self.rab_repo = RabRepository()

    async def handle_jira_event(
        self,
        issue_key: str,
        event_type: str | None,
        payload: dict,
    ) -> str:
        logger.info("Orchestrator received event: issue_key=%s, event_type=%s", issue_key, event_type)

        issue_data = await self._fetch_issue(issue_key)
        if not issue_data:
            return "error_fetching_issue_data"

        validation = self.field_validator.validate(issue_data)
        await self.rab_repo.record_validation(issue_key, validation.valid, validation.detail)
        if not validation.valid:
            msg = f"Validation failed.\n\n{validation.detail}\n\nPlease update the ticket and trigger re-check."
            await self._add_comment(issue_key, f"RAB Automation: {msg}")
            await self._send_card("Validation Failed", developer_notification_card(issue_key, validation.missing_fields))
            return f"validation_failed: {validation.detail}"

        await self._add_comment(issue_key, "RAB Automation: Ticket validation passed — starting approvals.")
        await self._send_card("Validation Passed", validation_passed_card(issue_key))

        summary = issue_data.get("fields", {}).get("summary", "No summary")
        self.approval_service.create_approval(issue_key, summary)

        await self._request_sdl_approval(issue_key, summary)
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

    async def _send_card(self, title: str, card: dict) -> None:
        if not self.teams_client._is_configured():
            return
        try:
            conv = get_conversation("channel")
            if conv:
                await self.teams_client.send_adaptive_card(conv, card)
            elif self.teams_client.settings.TEAMS_CHANNEL_ID:
                await self.teams_client.send_card_to_channel(
                    self.teams_client.settings.TEAMS_CHANNEL_ID, card,
                )
        except TeamsClientError as e:
            logger.error("Teams send failed: %s", e)

    async def _request_sdl_approval(self, issue_key: str, summary: str) -> None:
        approval_id = str(uuid.uuid4())
        self.approval_service.record_approval_id(issue_key, approval_id)
        await self.rab_repo.upsert_record(issue_key, {"sdl_approval": "requested"})
        card = approval_request_card(issue_key, summary, "SDL", approval_id)
        await self._add_comment(issue_key, "RAB Automation: SDL approval requested.")
        await self._send_card(f"SDL Approval: {issue_key}", card)

    async def _request_sdm_approval(self, issue_key: str, summary: str) -> None:
        approval_id = str(uuid.uuid4())
        self.approval_service.record_approval_id(issue_key, approval_id)
        await self.rab_repo.upsert_record(issue_key, {"sdm_approval": "requested"})
        card = approval_request_card(issue_key, summary, "SDM", approval_id)
        await self._add_comment(issue_key, "RAB Automation: SDM approval requested.")
        await self._send_card(f"SDM Approval: {issue_key}", card)

    async def handle_approval_callback(
        self,
        issue_key: str,
        action: str,
        approver: str = "",
        reason: str | None = None,
    ) -> dict:
        state = self.approval_service.get_approval(issue_key)
        if not state:
            return {"status": "error", "detail": "No active approval"}

        step = "SDL" if state.current_step == ApprovalStep.SDL else "SDM"
        await self.rab_repo.record_approval_event(issue_key, step, action, approver, reason or "")

        result = self.approval_service.process_response(issue_key, action, reason)
        decision = result.get("decision")

        if decision == "rejected":
            rejected_by = result["rejected_by"]
            await self._add_comment(
                issue_key,
                f"RAB Automation: {rejected_by} rejected.\nReason: {reason or 'No reason provided.'}",
            )
            await self._send_card(
                f"Rejected: {issue_key}",
                rejection_notification_card(issue_key, rejected_by, reason),
            )
            return {"status": "rejected", "rejected_by": rejected_by, "detail": f"Rejected by {rejected_by}"}

        if decision == "approved":
            await self._add_comment(issue_key, f"RAB Automation: {step} approved.")
            await self._send_card(
                f"Approved by {step}: {issue_key}",
                validation_passed_card(issue_key),
            )

            next_step = result.get("next_step")
            if next_step == ApprovalStep.SDM.value:
                await self._request_sdm_approval(issue_key, state.summary)
                return {"status": "approved", "detail": "SDL approved — SDM approval requested", "next": "sdm"}
            else:
                await self._add_comment(issue_key, "RAB Automation: All approvals complete. Requesting meeting decision.")
                await self._request_meeting_decision(issue_key)
                return {"status": "approved", "detail": "All approvals complete", "next": "meeting_decision"}

        return {"status": "error", "detail": result.get("error", "Unknown")}

    async def _request_meeting_decision(self, issue_key: str) -> None:
        card = meeting_decision_card(issue_key)
        await self._send_card(f"Meeting Decision: {issue_key}", card)
        await self._add_comment(issue_key, "RAB Automation: Meeting decision requested.")

    async def handle_meeting_callback(self, issue_key: str, needs_meeting: bool) -> str:
        await self.rab_repo.upsert_record(issue_key, {
            "meeting_needed": 1 if needs_meeting else 0,
            "status": "meeting_scheduled" if needs_meeting else "release_ready",
        })
        if needs_meeting:
            await self._add_comment(issue_key, "RAB Automation: Meeting will be scheduled. Resolving attendees from ticket.")
            await self._send_card(
                "Meeting Needed",
                {"type": "AdaptiveCard", "version": "1.4", "body": [{"type": "TextBlock", "text": f"Meeting required for {issue_key}. Resolve attendees from ticket fields."}]},
            )
            return "meeting_scheduled"
        else:
            await self._add_comment(issue_key, "RAB Automation: No meeting needed — release ticket finalized.")
            await self._send_card(
                "Release Ready",
                {"type": "AdaptiveCard", "version": "1.4", "body": [{"type": "TextBlock", "text": f"Release ticket {issue_key} is ready for deployment."}]},
            )
            return "release_ready"
