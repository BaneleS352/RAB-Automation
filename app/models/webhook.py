"""Pydantic models for Jira webhook payloads."""

from pydantic import BaseModel


class JiraIssuePayload(BaseModel):
    """Represents the issue object inside a Jira webhook payload."""

    model_config = {"extra": "allow"}

    key: str | None = None


class JiraWebhookPayload(BaseModel):
    """Top-level Jira webhook payload.

    Configured to allow extra fields since Jira payloads
    contain many additional properties we don't need yet.
    """

    model_config = {"extra": "allow"}

    webhookEvent: str | None = None
    issue: JiraIssuePayload | None = None
