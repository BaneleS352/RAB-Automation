"""Approval state machine — tracks SDL → SDM sequential approvals per issue."""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

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


_store: dict[str, ApprovalState] = {}


class ApprovalService:
    """Manages sequential SDL → SDM approval workflow for a ticket."""

    def create_approval(self, issue_key: str, summary: str) -> ApprovalState:
        state = ApprovalState(issue_key=issue_key, summary=summary)
        _store[issue_key] = state
        logger.info("Approval created for %s: current_step=%s", issue_key, state.current_step.value)
        return state

    def get_approval(self, issue_key: str) -> ApprovalState | None:
        return _store.get(issue_key)

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
        _store.clear()
