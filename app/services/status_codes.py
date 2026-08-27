"""Centralized status vocabulary for the RAB workflow."""

from enum import Enum


class RabStatus(str, Enum):
    """Canonical status values for RAB records and events."""

    PENDING = "pending"
    VALIDATED = "validated"
    VALIDATION_FAILED = "validation_failed"
    SDL_REQUESTED = "sdl_requested"
    SDL_APPROVED = "sdl_approved"
    SDL_REJECTED = "sdl_rejected"
    SDM_REQUESTED = "sdm_requested"
    SDM_APPROVED = "sdm_approved"
    SDM_REJECTED = "sdm_rejected"
    RELEASE_READY = "release_ready"
    MEETING_SCHEDULED = "meeting_scheduled"

    # Derived/combined statuses used in orchestration responses
    SDL_FLOW_STARTED = "approval_requested_sdl"


def is_pending(status: str | None) -> bool:
    """Check whether a status string indicates a pending state."""
    return status == RabStatus.PENDING.value


def is_sdl_requested(status: str | None) -> bool:
    """Check whether a status string indicates SDL approval is requested."""
    return status == RabStatus.SDL_REQUESTED.value


KNOWN_STATUSES: list[str] = [
    RabStatus.PENDING.value,
    RabStatus.VALIDATED.value,
    RabStatus.VALIDATION_FAILED.value,
    RabStatus.SDL_REQUESTED.value,
    RabStatus.SDL_APPROVED.value,
    RabStatus.SDL_REJECTED.value,
    RabStatus.SDM_REQUESTED.value,
    RabStatus.SDM_APPROVED.value,
    RabStatus.SDM_REJECTED.value,
    RabStatus.RELEASE_READY.value,
    RabStatus.MEETING_SCHEDULED.value,
]


def from_record(value: str) -> RabStatus | None:
    """Convert a DB record status string to a RabStatus enum member."""
    try:
        return RabStatus(value)
    except ValueError:
        return None


# Centralized derived vocabularies — single source of truth for repository/dashboard/orchestrator
FAILURE_STATUSES: tuple[str, ...] = (
    RabStatus.VALIDATION_FAILED.value,
    RabStatus.SDL_REJECTED.value,
    RabStatus.SDM_REJECTED.value,
)

FLOW_STATUSES: tuple[str, ...] = (
    RabStatus.SDL_REQUESTED.value,
    RabStatus.SDM_REQUESTED.value,
    RabStatus.SDL_APPROVED.value,
    RabStatus.SDM_APPROVED.value,
    RabStatus.SDL_REJECTED.value,
    RabStatus.SDM_REJECTED.value,
    RabStatus.RELEASE_READY.value,
    RabStatus.MEETING_SCHEDULED.value,
)

PENDING_APPROVAL_WHERE = "sdl_approval = 'requested' OR sdm_approval = 'requested'"

def is_flow_status(status: str | None) -> bool:
    return status in FLOW_STATUSES

def is_failure_status(status: str | None) -> bool:
    return status in FAILURE_STATUSES