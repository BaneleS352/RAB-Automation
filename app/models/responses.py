"""Pydantic response models for the RAB Automation API."""

from pydantic import BaseModel


class JiraConnectionInfo(BaseModel):
    """Jira API connection status."""

    connected: bool
    details: str


class TeamsConnectionInfo(BaseModel):
    """Teams workflow webhook status, split by direction.

    `connected`/`details` keep their legacy outbound meaning so existing
    consumers are unaffected. Direction fields are required (no defaults) so
    they are always serialized despite HealthResponse's exclude_defaults —
    the Overview card and monitors must always see which way Teams flows.
    """

    connected: bool
    details: str
    # False when no webhook URL is set at all — informational, never degrades
    # overall health. Defaults True so existing payloads stay unchanged
    # (exclude_defaults omits it unless explicitly False).
    configured: bool = True
    # "unconfigured" | "outbound-only" | "two-way" (workflow webhooks are
    # POST-only, so "two-way" requires a mounted callback receiver).
    direction: str
    # Human-readable outbound assessment (alerts RAB → Teams).
    outbound_details: str
    # True only when Teams can send decisions back (approval-through-Teams).
    inbound_supported: bool
    # Human-readable inbound assessment, incl. what is missing to enable it.
    inbound_details: str


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
