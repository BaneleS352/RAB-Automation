"""Pydantic models for Jira webhook payloads."""

import re

from pydantic import BaseModel, Field, field_validator


ISSUE_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$")


class JiraIssuePayload(BaseModel):
    """Represents the issue object inside a Jira webhook payload."""

    model_config = {"extra": "allow"}

    key: str | None = Field(None, max_length=128, description="Jira issue key, e.g. PROJ-123")

    @field_validator("key")
    @classmethod
    def validate_issue_key(cls, v: str | None) -> str | None:
        if v is not None and not ISSUE_KEY_PATTERN.match(v):
            raise ValueError(f"Invalid issue key format: {v}")
        return v


class JiraWebhookPayload(BaseModel):
    """Top-level Jira webhook payload.

    Configured to allow extra fields since Jira payloads
    contain many additional properties we don't need yet.
    """

    model_config = {"extra": "allow"}

    webhookEvent: str | None = None
    issue: JiraIssuePayload | None = None
