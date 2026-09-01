"""RAB Orchestrator – processes Jira events through the full RAB workflow (monitor mode)."""

import asyncio
import json
import logging
import uuid

from app.config import get_settings
from app.repositories.rab_repository import RabRepository
from app.services.approval_service import ApprovalService, ApprovalStep
from app.services.field_validator import FieldValidator
from app.services.jira_client import JiraClient, JiraClientError
from app.services.jira_fields import adf_to_text
from app.services.status_codes import FLOW_STATUSES, RabStatus


def _extract_rich_fields_orch(issue: dict, fv: FieldValidator) -> dict:
    fields = issue.get("fields", {}) or {}
    summary = fields.get("summary", "") or ""
    description = adf_to_text(fields.get("description"))
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
    # RAB snapshot for raw_fields
    from app.services.field_validator import REQUIRED_FIELDS

    rab_snapshot: dict[str, str | None] = {}
    for _, key in REQUIRED_FIELDS:
        try:
            rab_snapshot[key] = fv.extract_field_value(issue, key)
        except Exception:
            rab_snapshot[key] = None
    raw_fields = json.dumps({"rab_fields": rab_snapshot, "field_map": getattr(fv, "field_map", {}), "labels": labels}, ensure_ascii=False)[:4000]
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
            # Fetch outside lock to avoid blocking concurrent webhooks for same key during network I/O
            issue_data = await self._fetch_issue(issue_key)
            if not issue_data:
                return "monitored"
            validation = self.field_validator.validate(issue_data)
            rich = _extract_rich_fields_orch(issue_data, self.field_validator)
            # Advisory: always NOTE present/missing (per drawio: GET and NOTE), do not hard-fail on missing.
            # Store advisory detail even when valid but with missing_fields so dashboard shows completeness.
            strict = bool(getattr(get_settings(), "RAB_STRICT_VALIDATION", False))
            if strict:
                val_result = validation.detail if not validation.valid else ""
                status = "validated" if validation.valid else "validation_failed"
            else:
                # Advisory: validated_with_notes when any missing, else validated
                if validation.missing_fields:
                    val_result = validation.detail
                    status = "validated_with_notes"
                else:
                    val_result = ""
                    status = "validated"
            lock = await _get_issue_lock(issue_key)
            async with lock:
                # Single write: preserve flow status if already in flow, else use new validation status
                existing = await self.rab_repo.get_record(issue_key)
                if existing and existing.get("status") in FLOW_STATUSES:
                    status = existing["status"]
                    # Keep existing validation_result if flow already started? No, update with new audit
                await self.rab_repo.upsert_record(issue_key, {
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
                    "validation_result": val_result,
                    "status": status,
                })
            return "monitored"

        # Fast path: check in-memory/DB without lock first to avoid holding lock during Jira fetch
        existing = self.approval_service.get_approval(issue_key)
        if existing is not None:
            logger.info("Workflow already started for %s — ignoring start event %s", issue_key, event_type)
            return "already_in_progress"
        record = await self.rab_repo.get_record(issue_key)
        if record and (
            record.get("sdl_approval") in ("requested", "approved", "rejected")
            or record.get("sdm_approval") in ("requested", "approved", "rejected")
        ):
            logger.info("Workflow already started for %s — ignoring start event %s (DB)", issue_key, event_type)
            self.approval_service.load_from_record(record)
            return "already_in_progress"

        issue_data = await self._fetch_issue(issue_key)
        if not issue_data:
            return "error_fetching_issue_data"

        lock = await _get_issue_lock(issue_key)
        async with lock:
            # Re-check after acquiring lock (double-checked locking) to handle race where concurrent start created approval between fetch and lock
            existing = self.approval_service.get_approval(issue_key)
            if existing is not None:
                logger.info("Workflow already started for %s — ignoring start event %s (race)", issue_key, event_type)
                return "already_in_progress"
            record = await self.rab_repo.get_record(issue_key)
            if record and (
                record.get("sdl_approval") in ("requested", "approved", "rejected")
                or record.get("sdm_approval") in ("requested", "approved", "rejected")
            ):
                logger.info("Workflow already started for %s — ignoring start event %s (race DB)", issue_key, event_type)
                self.approval_service.load_from_record(record)
                return "already_in_progress"
            # No prior state — proceed with new workflow (validation and rich fields already fetched)

            validation = self.field_validator.validate(issue_data)
            rich = _extract_rich_fields_orch(issue_data, self.field_validator)
            # Persist all rich Jira details so dashboard no longer shows blank; previously only creator/assignee were saved
            await self.rab_repo.upsert_record(issue_key, {
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
            })
            # Advisory: when valid True but missing fields, store as validated_with_notes (per drawio: GET and NOTE)
            if validation.valid and validation.missing_fields:
                await self.rab_repo.upsert_record(issue_key, {
                    "status": "validated_with_notes",
                    "validation_result": validation.detail,
                })
            else:
                await self.rab_repo.record_validation(issue_key, validation.valid, validation.detail)
            # Advisory mode (default): GET ticket and NOTE which RAB fields are present/missing (per data structure.drawio.html),
            # do NOT block workflow. Strict mode (RAB_STRICT_VALIDATION=True) retains old hard-fail.
            strict = bool(getattr(get_settings(), "RAB_STRICT_VALIDATION", False))
            if not validation.valid and strict:
                msg = f"Validation failed.\n\n{validation.detail}\n\nPlease update the ticket and trigger re-check."
                await self._add_comment(issue_key, f"RAB Automation: {msg}")
                await self._send_card("Validation Failed")
                await self._maybe_transition(issue_key, "JIRA_TRANSITION_REJECT")
                return f"validation_failed: {validation.detail}"
            # Advisory: always continue, but add a Jira comment noting completeness (fixes blank-details by surfacing it)
            if validation.missing_fields:
                await self._add_comment(issue_key, f"RAB Automation: {validation.detail}\n\nWorkflow continues (advisory mode — set RAB_STRICT_VALIDATION=true to block on missing fields).")
                await self._send_card(f"RAB audit noted — {len(validation.missing_fields)} field(s) missing, proceeding")
            else:
                await self._maybe_transition(issue_key, "JIRA_TRANSITION_VALIDATE")
                await self._add_comment(issue_key, "RAB Automation: Ticket validation passed — starting approvals.")
                await self._send_card("Validation Passed")

            summary = issue_data.get("fields", {}).get("summary", "No summary")
            self.approval_service.create_approval(issue_key, summary)

            await self._maybe_transition(issue_key, "JIRA_TRANSITION_REQUEST_APPROVAL")
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

    async def _maybe_transition(self, issue_key: str, transition_env: str) -> None:
        """Attempt a Jira workflow transition if its ID is configured; otherwise no-op (previously dead code)."""
        settings = get_settings()
        tid = getattr(settings, transition_env, "") or ""
        if not tid:
            logger.debug("Skipping Jira transition %s for %s — %s not configured (was dead code before)", transition_env, issue_key, transition_env)
            return
        try:
            await self.jira_client.transition_issue(issue_key, tid)
            logger.info("Jira transition %s (%s) applied to %s", transition_env, tid, issue_key)
        except JiraClientError as e:
            logger.warning("Jira transition %s for %s failed (id=%s): %s", transition_env, issue_key, tid, e)

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
                await self._maybe_transition(issue_key, "JIRA_TRANSITION_REJECT")
                await self._add_comment(
                    issue_key,
                    f"RAB Automation: {rejected_by} rejected.\nReason: {reason or 'No reason provided.'}",
                )
                await self._send_card(f"Rejected: {issue_key}")
                return {"status": "rejected", "rejected_by": rejected_by, "detail": f"Rejected by {rejected_by}"}

            if decision == "approved":
                await self._maybe_transition(issue_key, "JIRA_TRANSITION_APPROVE")
                await self._add_comment(issue_key, f"RAB Automation: {step} approved.")
                await self._send_card(f"Approved by {step}: {issue_key}")

                next_step = result.get("next_step")
                if next_step == ApprovalStep.SDM.value:
                    await self._maybe_transition(issue_key, "JIRA_TRANSITION_REQUEST_APPROVAL")
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
                # Teams alerting basis only — final release state (per user request; re-uses send_to_teams.py workflow pattern)
                try:
                    from app.services.teams_alert import send_release_ready_alert

                    record = await self.rab_repo.get_record(issue_key)
                    summary = record.get("summary") if record else ""
                    details = {
                        "jira_status": record.get("jira_status") if record else "",
                        "issuetype": record.get("issuetype") if record else "",
                        "priority": record.get("priority") if record else "",
                        "assignee": record.get("assignee") if record else "",
                        "reporter": record.get("reporter") if record else "",
                        "environment": "",
                        "labels": record.get("labels") if record else "",
                        "validation_result": record.get("validation_result") if record else "",
                    }
                    # Try to enrich environment from raw_fields if available
                    if record and record.get("raw_fields"):
                        try:
                            import json as _json

                            raw = _json.loads(record["raw_fields"])
                            env_val = (raw.get("rab_fields") or {}).get("environment")
                            if env_val:
                                details["environment"] = env_val
                        except Exception:
                            pass
                    await send_release_ready_alert(issue_key, summary, details)
                except Exception as e:
                    logger.warning("Teams release alert wiring for %s failed (non-blocking): %s", issue_key, e)
                return "release_ready"
