"""Jira webhook endpoint with idempotency support."""

import logging
import uuid

from fastapi import APIRouter, Header

from app.exceptions import MissingIssueKeyError
from app.models.responses import JiraWebhookResponse
from app.models.webhook import JiraWebhookPayload
from app.repositories.rab_repository import RabRepository
from app.services.rab_orchestrator import RabOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

orchestrator = RabOrchestrator()
rab_repo = RabRepository()


@router.post("/jira", response_model=JiraWebhookResponse)
async def jira_webhook(
    payload: JiraWebhookPayload,
    x_idempotency_key: str | None = Header(None),
):
    issue_key: str | None = None
    if payload.issue is not None:
        issue_key = payload.issue.key

    if not issue_key:
        logger.warning("Webhook payload missing Jira issue key")
        raise MissingIssueKeyError()

    event_id = x_idempotency_key or str(uuid.uuid4())

    if x_idempotency_key:
        seen = await rab_repo.record_webhook_event(event_id, issue_key, payload.webhookEvent or "")
        if not seen:
            logger.info("Duplicate webhook (idempotency_key=%s) — returning cached result", event_id)
            record = await rab_repo.get_record(issue_key)
            if record:
                return JiraWebhookResponse(
                    status="accepted",
                    issue_key=issue_key,
                    event_type=payload.webhookEvent,
                    result=record["status"],
                    idempotent_replay=True,
                )

    logger.info("Received Jira webhook: issue_key=%s, event=%s, idempotency_key=%s", issue_key, payload.webhookEvent, event_id)

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
        idempotent_replay=False,
    )
