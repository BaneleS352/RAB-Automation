"""Approval state machine — tracks SDL → SDM sequential approvals per issue."""

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ApprovalStep(str, Enum):
    SDL = "SDL"
    SDM = "SDM"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class ApprovalState:
    issue_key: str
    summary: str = ""
    sdl_status: ApprovalStatus = ApprovalStatus.PENDING
    sdm_status: ApprovalStatus = ApprovalStatus.PENDING
    current_step: ApprovalStep = ApprovalStep.SDL
    rejection_reason: str | None = None
    rejected_by: str | None = None
    sdl_approval_id: str = ""
    sdm_approval_id: str = ""


_store: dict[str, ApprovalState] = {}  # deprecated global, kept for backward compat


class ApprovalService:
    """Manages sequential SDL → SDM approval workflow for a ticket."""

    def __init__(self) -> None:
        # Instance store for isolation; falls back to global for cross-instance hydration
        self._store: dict[str, ApprovalState] = {}

    def _get_store(self) -> dict[str, ApprovalState]:
        # Prefer instance store, but check global for hydration after restart
        return self._store

    def create_approval(self, issue_key: str, summary: str) -> ApprovalState:
        store = self._get_store()
        existing = store.get(issue_key) or _store.get(issue_key)
        if existing is not None:
            logger.info(
                "Approval already exists for %s — refusing to overwrite (current_step=%s)",
                issue_key, existing.current_step.value,
            )
            return existing
        state = ApprovalState(issue_key=issue_key, summary=summary)
        self._store[issue_key] = state
        _store[issue_key] = state
        logger.info("Approval created for %s: current_step=%s", issue_key, state.current_step.value)
        return state

    def get_approval(self, issue_key: str) -> ApprovalState | None:
        return self._store.get(issue_key) or _store.get(issue_key)

    @staticmethod
    def _db_status(value: str) -> ApprovalStatus:
        if value == ApprovalStatus.APPROVED.value:
            return ApprovalStatus.APPROVED
        if value == ApprovalStatus.REJECTED.value:
            return ApprovalStatus.REJECTED
        return ApprovalStatus.PENDING

    def load_from_record(self, record: dict) -> ApprovalState | None:
        """Reconstruct approval state from a ``rab_records`` row after restart.

        Returns ``None`` when no approval step was ever requested, in which case
        the callback is not part of an active workflow.
        """
        issue_key = record.get("issue_key")
        if not issue_key:
            return None
        raw_sdl = record.get("sdl_approval") or ""
        raw_sdm = record.get("sdm_approval") or ""
        started = raw_sdl in ("requested", "approved", "rejected") or raw_sdm in ("requested", "approved", "rejected")
        if not started:
            return None
        sdl = self._db_status(raw_sdl)
        sdm = self._db_status(raw_sdm)
        if sdl == ApprovalStatus.PENDING or sdl == ApprovalStatus.REJECTED:
            current_step = ApprovalStep.SDL
        else:
            current_step = ApprovalStep.SDM
        state = ApprovalState(
            issue_key=issue_key,
            summary=record.get("summary", ""),
            sdl_status=sdl,
            sdm_status=sdm,
            current_step=current_step,
            rejection_reason=record.get("rejection_reason") or None,
            rejected_by=record.get("rejected_by") or None,
            sdl_approval_id=record.get("sdl_approval_id") or "",
            sdm_approval_id=record.get("sdm_approval_id") or "",
        )
        self._store[issue_key] = state
        _store[issue_key] = state
        logger.info(
            "Approval state hydrated for %s: sdl=%s sdm=%s current_step=%s",
            issue_key, sdl.value, sdm.value, current_step.value,
        )
        return state

    def get_current_step(self, issue_key: str) -> ApprovalStep | None:
        state = self.get_approval(issue_key)
        return state.current_step if state else None

    def get_current_approver(self, issue_key: str) -> str | None:
        step = self.get_current_step(issue_key)
        return step.value if step else None

    def record_approval_id(self, issue_key: str, approval_id: str) -> None:
        state = self.get_approval(issue_key)
        if not state:
            return
        if state.current_step == ApprovalStep.SDL:
            state.sdl_approval_id = approval_id
        else:
            state.sdm_approval_id = approval_id

    def process_response(self, issue_key: str, action: str, reason: str | None = None) -> dict:
        state = self.get_approval(issue_key)
        if not state:
            return {"error": "No active approval for this issue"}

        step = state.current_step
        step_status = state.sdl_status if step == ApprovalStep.SDL else state.sdm_status

        if step_status != ApprovalStatus.PENDING:
            logger.warning(
                "Ignoring %s for %s — %s is already %s", action, issue_key, step.value, step_status.value,
            )
            return {"error": f"{step.value} is already {step_status.value}", "next_step": None}

        if action == "reject":
            state.rejection_reason = reason
            state.rejected_by = step.value
            if step == ApprovalStep.SDL:
                state.sdl_status = ApprovalStatus.REJECTED
            else:
                state.sdm_status = ApprovalStatus.REJECTED
            logger.info("Approval %s REJECTED by %s: %s", issue_key, step.value, reason)
            return {
                "decision": "rejected",
                "rejected_by": step.value,
                "reason": reason,
                "next_step": None,
            }

        if action == "approve":
            if step == ApprovalStep.SDL:
                state.sdl_status = ApprovalStatus.APPROVED
                state.current_step = ApprovalStep.SDM
                logger.info("SDL approved for %s — moving to SDM", issue_key)
                return {
                    "decision": "approved",
                    "rejected_by": None,
                    "reason": None,
                    "next_step": ApprovalStep.SDM.value,
                }
            else:
                state.sdm_status = ApprovalStatus.APPROVED
                logger.info("SDM approved for %s — all approvals complete", issue_key)
                return {
                    "decision": "approved",
                    "rejected_by": None,
                    "reason": None,
                    "next_step": None,
                }

        return {"error": f"Unknown action: {action}"}

    def is_fully_approved(self, issue_key: str) -> bool:
        state = self.get_approval(issue_key)
        return bool(state and state.sdl_status == ApprovalStatus.APPROVED and state.sdm_status == ApprovalStatus.APPROVED)

    def is_rejected(self, issue_key: str) -> bool:
        state = self.get_approval(issue_key)
        return bool(state and (state.sdl_status == ApprovalStatus.REJECTED or state.sdm_status == ApprovalStatus.REJECTED))

    def reset(self) -> None:
        self._store.clear()
        _store.clear()

    def reset_issue(self, issue_key: str) -> None:
        self._store.pop(issue_key, None)
        _store.pop(issue_key, None)
