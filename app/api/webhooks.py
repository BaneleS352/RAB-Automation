"""Jira webhook endpoint."""

import logging

from fastapi import APIRouter

from app.exceptions import MissingIssueKeyError
from app.models.responses import JiraWebhookResponse
from app.models.webhook import JiraWebhookPayload
from app.services.rab_orchestrator import RabOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Single orchestrator instance; can be replaced with DI in later phases.
orchestrator = RabOrchestrator()


@router.post("/jira", response_model=JiraWebhookResponse)
async def jira_webhook(payload: JiraWebhookPayload) -> JiraWebhookResponse:
    """Receive and process a Jira webhook event.

    Steps:
      1. Extract the Jira issue key from the payload.
      2. Delegate processing to the RabOrchestrator.
      3. Return a structured response.
    """
    issue_key: str | None = None
    if payload.issue is not None:
        issue_key = payload.issue.key

    if not issue_key:
        logger.warning("Webhook payload missing Jira issue key")
        raise MissingIssueKeyError()

    logger.info("Received Jira webhook: issue_key=%s, event=%s", issue_key, payload.webhookEvent)

    result = await orchestrator.handle_jira_event(
        issue_key=issue_key,
        event_type=payload.webhookEvent,
        payload=payload.model_dump(),
    )

    logger.info("Orchestration result for %s: %s", issue_key, result)

    return JiraWebhookResponse(
        status="accepted",
        issue_key=issue_key,
        event_type=payload.webhookEvent,
        result=result,
    )
