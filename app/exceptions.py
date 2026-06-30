"""Custom exceptions for the RAB Automation service."""

from fastapi import HTTPException, status


class UnauthorizedError(HTTPException):
    """Raised when webhook secret validation fails."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )


class MissingIssueKeyError(HTTPException):
    """Raised when the Jira webhook payload is missing an issue key."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Jira issue key in webhook payload",
        )
