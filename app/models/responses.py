"""Pydantic response models for the RAB Automation API."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response model for the health check endpoint."""

    status: str
    service: str
    environment: str


class RootResponse(BaseModel):
    """Response model for the root endpoint."""

    service: str
    status: str


class JiraWebhookResponse(BaseModel):
    """Response model for a successfully processed Jira webhook."""

    status: str
    issue_key: str
    event_type: str | None = None
    result: str
