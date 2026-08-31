"""Jira webhook endpoint with idempotency support."""

import asyncio
import hashlib
import json
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
                evicted = False
                for existing_id in list(_event_locks):
                    if not _event_locks[existing_id].locked():
                        del _event_locks[existing_id]
                        evicted = True
                        break
                if not evicted:
                    # All locks are held — avoid unbounded growth by not caching new lock (ad-hoc)
                    return asyncio.Lock()
            lock = asyncio.Lock()
            _event_locks[event_id] = lock
        return lock


def _stable_payload_hash(payload: JiraWebhookPayload) -> str:
    """Hash only stable fields for idempotency — not transient timestamps."""
    changelog = payload.model_extra.get("changelog") or {}
    items = []
    if isinstance(changelog.get("items"), list):
        for it in changelog["items"]:
            if isinstance(it, dict):
                items.append((it.get("field"), it.get("fromString") or it.get("from"), it.get("toString") or it.get("to")))
    stable = {
        "key": payload.issue.key if payload.issue else None,
        "event": payload.webhookEvent,
        "changelog": sorted(items),
    }
    return hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode()).hexdigest()[:32]


async def _process_webhook(
    event_id: str,
    issue_key: str,
    payload: JiraWebhookPayload,
) -> JiraWebhookResponse:
    # Always treat as keyed — deterministic fallback hash makes retries idempotent (fixes dead else branch)
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

    logger.info("Received Jira webhook: issue_key=%s, event=%s, idempotency_key=%s", issue_key, payload.webhookEvent, event_id)

    changelog = payload.model_extra.get("changelog")
    if not changelog or not isinstance(changelog.get("items"), list) or not changelog.get("items"):
        logger.info("Webhook for %s has no changelog (Jira webhook may not be configured to send changelog — field_changes will be empty; configure Jira webhook to 'Send changelog' or rely on sync)", issue_key)
    await rab_repo.record_field_changes(issue_key, changelog)

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

    if x_idempotency_key:
        event_id = x_idempotency_key
    else:
        try:
            digest = _stable_payload_hash(payload)
            event_id = f"auto:{digest}"
        except Exception:
            event_id = str(uuid.uuid4())

    lock = _get_event_lock(event_id)
    async with lock:
        return await _process_webhook(event_id, issue_key, payload)
