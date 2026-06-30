"""Jira webhook endpoint with shared-secret validation."""

import hmac
import logging

from fastapi import APIRouter, Header, Request

from app.exceptions import MissingIssueKeyError, UnauthorizedError
from app.models.responses import JiraWebhookResponse
from app.models.webhook import JiraWebhookPayload
from app.services.rab_orchestrator import RabOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Single orchestrator instance – can be replaced with DI in later phases
orchestrator = RabOrchestrator()


def _validate_secret(provided: str | None, expected: str) -> None:
    """Validate the webhook shared secret using constant-time comparison.

    Raises UnauthorizedError if the secret is missing or does not match.
    Never logs the actual secret values.
    """
    if provided is None:
        logger.warning("Webhook request missing secret header")
        raise UnauthorizedError()

    if not hmac.compare_digest(provided, expected):
        logger.warning("Webhook request had invalid secret")
        raise UnauthorizedError()


@router.post("/jira", response_model=JiraWebhookResponse)
async def jira_webhook(
    request: Request,
    payload: JiraWebhookPayload,
    x_rab_automation_secret: str | None = Header(None),
) -> JiraWebhookResponse:
    """Receive and process a Jira webhook event.

    Steps:
      1. Validate the shared secret from the X-RAB-Automation-Secret header.
      2. Extract the Jira issue key from the payload.
      3. Delegate processing to the RabOrchestrator.
      4. Return a structured response.
    """
    settings = request.app.state.settings

    # 1. Validate secret
    _validate_secret(x_rab_automation_secret, settings.JIRA_WEBHOOK_SHARED_SECRET)

    # 2. Extract issue key
    issue_key: str | None = None
    if payload.issue is not None:
        issue_key = payload.issue.key

    if not issue_key:
        logger.warning("Webhook payload missing Jira issue key")
        raise MissingIssueKeyError()

    logger.info("Received Jira webhook: issue_key=%s, event=%s", issue_key, payload.webhookEvent)

    # 3. Hand off to orchestrator
    result = await orchestrator.handle_jira_event(
        issue_key=issue_key,
        event_type=payload.webhookEvent,
        payload=payload.model_dump(),
    )

    logger.info("Orchestration result for %s: %s", issue_key, result)

    # 4. Structured response
    return JiraWebhookResponse(
        status="accepted",
        issue_key=issue_key,
        event_type=payload.webhookEvent,
        result=result,
    )
