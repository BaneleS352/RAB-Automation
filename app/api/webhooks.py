"""Jira webhook endpoint with idempotency support."""

import asyncio
import logging
import threading
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

_event_locks: dict[str, asyncio.Lock] = {}
_MAX_EVENT_LOCKS = 1024
_locks_lock = threading.Lock()


def _get_event_lock(event_id: str) -> asyncio.Lock:
    """Per-event-id lock so concurrent retries of the same webhook serialize.

    Lock entries are evicted oldest-first once the map is full, but only
    unlocked entries are eligible — a held lock must not be dropped while a
    webhook is still being processed.
    """
    with _locks_lock:
        lock = _event_locks.get(event_id)
        if lock is None:
            if len(_event_locks) >= _MAX_EVENT_LOCKS:
                for existing_id in list(_event_locks):
                    if not _event_locks[existing_id].locked():
                        del _event_locks[existing_id]
                        break
            lock = asyncio.Lock()
            _event_locks[event_id] = lock
        return lock


async def _process_webhook(
    event_id: str,
    issue_key: str,
    payload: JiraWebhookPayload,
    keyed: bool,
) -> JiraWebhookResponse:
    if keyed:
        seen = await rab_repo.record_webhook_event(event_id, issue_key, payload.webhookEvent or "")
        if not seen:
            logger.info("Duplicate webhook (idempotency_key=%s) — returning cached result", event_id)
            event = await rab_repo.get_webhook_event(event_id)
            if event:
                result = event.get("status") or ""
                if not result:
                    record = await rab_repo.get_record(issue_key)
                    result = record["status"] if record else ""
                return JiraWebhookResponse(
                    status="accepted",
                    issue_key=issue_key,
                    event_type=payload.webhookEvent,
                    result=result,
                    idempotent_replay=True,
                )
    else:
        await rab_repo.record_webhook_event(event_id, issue_key, payload.webhookEvent or "")

    logger.info("Received Jira webhook: issue_key=%s, event=%s, idempotency_key=%s", issue_key, payload.webhookEvent, event_id)

    await rab_repo.record_field_changes(issue_key, payload.model_extra.get("changelog"))

    result = await orchestrator.handle_jira_event(
        issue_key=issue_key,
        event_type=payload.webhookEvent,
    )

    logger.info("Orchestration result for %s: %s", issue_key, result)
    await rab_repo.update_webhook_event_status(event_id, result)

    return JiraWebhookResponse(
        status="accepted",
        issue_key=issue_key,
        event_type=payload.webhookEvent,
        result=result,
        idempotent_replay=False,
    )


@router.post("/jira", response_model=JiraWebhookResponse)
async def jira_webhook(
    payload: JiraWebhookPayload,
    x_idempotency_key: str | None = Header(None),
) -> JiraWebhookResponse:
    issue_key: str | None = None
    if payload.issue is not None:
        issue_key = payload.issue.key

    if not issue_key:
        logger.warning("Webhook payload missing Jira issue key")
        raise MissingIssueKeyError()

    event_id = x_idempotency_key or str(uuid.uuid4())

    if x_idempotency_key:
        lock = _get_event_lock(event_id)
        async with lock:
            return await _process_webhook(event_id, issue_key, payload, keyed=True)

    return await _process_webhook(event_id, issue_key, payload, keyed=False)
