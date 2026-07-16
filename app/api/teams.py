"""Bot Framework webhook endpoint — receives Teams interactions."""

import logging

from fastapi import APIRouter, Request

from app.services.teams_client import ConversationReference, register_conversation
from app.services.rab_orchestrator import RabOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

orchestrator = RabOrchestrator()


@router.post("/teams")
async def teams_webhook(request: Request) -> dict:
    """Receive Bot Framework activities (card clicks, messages)."""
    body = await request.json()
    activity_type = body.get("type", "")
    logger.info("Teams activity received: type=%s", activity_type)

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

    elif activity_type == "message":
        value = body.get("value", {})
        action = value.get("action", "")
        from_user = body.get("from", {}).get("name", "unknown")

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

        elif action == "meeting_yes":
            issue_key = value.get("issue_key", "")
            result = await orchestrator.handle_meeting_callback(issue_key, needs_meeting=True)
            return {"status": "ok", "detail": result}

        elif action == "meeting_no":
            issue_key = value.get("issue_key", "")
            result = await orchestrator.handle_meeting_callback(issue_key, needs_meeting=False)
            return {"status": "ok", "detail": result}

    return {"status": "ok"}
