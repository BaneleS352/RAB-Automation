"""Pydantic response models for the RAB Automation API."""

from pydantic import BaseModel


class JiraConnectionInfo(BaseModel):
    """Jira API connection status."""

    connected: bool
    details: str


class TeamsConnectionInfo(BaseModel):
    """Teams workflow webhook status (alerting basis only)."""

    connected: bool
    details: str


class HealthResponse(BaseModel):
    """Response model for the health check endpoint."""

    status: str
    service: str
    environment: str
    jira: JiraConnectionInfo | None = None
    teams: TeamsConnectionInfo | None = None

    model_config = {"exclude_defaults": True}


class JiraWebhookResponse(BaseModel):
    """Response model for a successfully processed Jira webhook."""

    status: str
    issue_key: str
    event_type: str | None = None
    result: str
    idempotent_replay: bool = False
