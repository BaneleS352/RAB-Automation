"""Teams webhook endpoint — receives Bot Framework activities and MessageCard HttpPOST callbacks."""

import json
import logging
from urllib.parse import parse_qs, unquote

from fastapi import APIRouter, Request

from app.services.rab_orchestrator import RabOrchestrator
from app.services.teams_client import ConversationReference, register_conversation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

orchestrator = RabOrchestrator()


def _decode_payload(raw: bytes, content_type: str) -> dict:
    """Decode a request body as JSON, tolerating MessageCard HttpPOST form-encoding."""
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        pass
    if "urlencoded" in content_type:
        decoded = unquote(raw.decode("utf-8"))
        try:
            return json.loads(decoded)
        except ValueError:
            pass
        form = parse_qs(decoded)
        for key, values in form.items():
            for item in [key, *values]:
                try:
                    return json.loads(item)
                except ValueError:
                    continue
    return {}


@router.post("/teams")
async def teams_webhook(request: Request) -> dict:
    """Receive Bot Framework activities (card clicks, messages) or MessageCard HttpPOST callbacks."""
    raw = await request.body()
    body = _decode_payload(raw, request.headers.get("content-type", ""))
    activity_type = body.get("type", "")
    logger.info("Teams activity received: type=%s, action=%s", activity_type, body.get("action", ""))

    if activity_type == "conversationUpdate":
        members = body.get("membersAdded", [])
        for member in members:
            if member.get("id") != body.get("recipient", {}).get("id"):
                ref = ConversationReference(
                    conversation_id=body.get("conversation", {}).get("id", ""),
                    service_url=body.get("serviceUrl", ""),
                    tenant_id=body.get("conversation", {}).get("tenantId", ""),
                    bot_id=body.get("recipient", {}).get("id", ""),
                    user_id=member.get("id", ""),
                )
                register_conversation(ref.user_id, ref)
                logger.info("Registered conversation for user: %s", member.get("name", ref.user_id))
        return {"status": "ok"}

    if activity_type == "message":
        value = body.get("value", {})
    else:
        # MessageCard HttpPOST callback: the payload itself carries the action.
        value = body

    action = value.get("action", "")
    from_user = body.get("from", {}).get("name") or value.get("user", "") or "Teams"

    if action in ("approve", "reject"):
        approval_id = value.get("approval_id", "")
        issue_key = value.get("issue_key", "")
        reason = value.get("reason", "")
        logger.info("Approval callback: action=%s, approval_id=%s, from=%s", action, approval_id, from_user)

        result = await orchestrator.handle_approval_callback(
            issue_key=issue_key,
            action=action,
            approver=from_user,
            reason=reason or None,
        )
        return {"status": result.get("status", "ok"), "detail": result.get("detail", "")}

    if action == "meeting_yes":
        issue_key = value.get("issue_key", "")
        result = await orchestrator.handle_meeting_callback(issue_key, needs_meeting=True)
        return {"status": "ok", "detail": result}

    if action == "meeting_no":
        issue_key = value.get("issue_key", "")
        result = await orchestrator.handle_meeting_callback(issue_key, needs_meeting=False)
        return {"status": "ok", "detail": result}

    return {"status": "ok"}