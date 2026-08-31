"""Teams alerting for final RAB state only (release_ready).

Re-uses the proven Power Automate workflow webhook pattern from scripts/send_to_teams.py
(AdaptiveCard POST to TEAMS_WORKFLOW_WEBHOOK_URL) but adapted to RAB release alerts.

Design: alert-only, not approval gating. Triggered only when a ticket transitions to
its final release state (release_ready). No-op when the webhook URL is not configured,
so local/dev and tests are unaffected. This keeps Teams to an alerting basis as requested,
rather than restoring the full approval-card flow.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(15.0)


def _build_release_card(issue_key: str, summary: str, details: dict[str, Any]) -> dict[str, Any]:
    """Build an AdaptiveCard payload for a release_ready ticket.

    Mirrors the working experiment's structure (type AdaptiveCard, schema 1.2) but
    replaces the generic Is this your choice? body with RAB release facts.
    The card posts back to the workflow URL only; actions are informational
    OpenUrl links to Jira and the local dashboard, not approval gating.
    """
    settings = get_settings()
    base_url = (settings.JIRA_BASE_URL or "https://yourcompany.atlassian.net").rstrip("/")
    jira_link = f"{base_url}/browse/{issue_key}"
    # Dashboard link uses the configured webhook URL's host if available
    dashboard_link = settings.JIRA_WEBHOOK_URL.replace("/webhooks/jira", f"/dashboard/records/{issue_key}") if settings.JIRA_WEBHOOK_URL else f"/dashboard/records/{issue_key}"

    # Facts for the card — keep to the notable RAB fields that were previously blank/noted
    facts = [
        {"title": "Issue", "value": issue_key},
        {"title": "Summary", "value": summary or "—"},
    ]
    # Only add non-empty details
    for label, key in [
        ("Jira status", "jira_status"),
        ("Issue type", "issuetype"),
        ("Priority", "priority"),
        ("Assignee", "assignee"),
        ("Reporter", "reporter"),
        ("Environment", "environment"),
        ("Labels", "labels"),
    ]:
        val = details.get(key)
        if val:
            facts.append({"title": label, "value": str(val)[:120]})

    # Include a truncated validation note if present (advisory audit)
    validation = details.get("validation_result")
    if validation:
        facts.append({"title": "RAB audit", "value": validation[:180]})

    # Include Jira link explicitly as a fact as well for non-action clients
    facts.append({"title": "Jira link", "value": jira_link})

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": f"🚀 RAB Release Ready — {issue_key}",
                "size": "Medium",
                "weight": "Bolder",
                "wrap": True,
                "color": "Good",
            },
            {
                "type": "TextBlock",
                "text": summary or "No summary",
                "wrap": True,
                "isSubtle": True,
                "spacing": "Small",
            },
            {"type": "FactSet", "facts": facts},
            {
                "type": "TextBlock",
                "text": "This ticket has passed SDL → SDM and requires no meeting. It is now **release_ready**.",
                "wrap": True,
                "size": "Small",
                "isSubtle": True,
                "spacing": "Medium",
            },
        ],
        "actions": [
            {"type": "Action.OpenUrl", "title": "View in Jira", "url": jira_link},
            {"type": "Action.OpenUrl", "title": "Open RAB dashboard", "url": dashboard_link},
        ],
    }


async def send_release_ready_alert(issue_key: str, summary: str = "", details: dict[str, Any] | None = None) -> bool:
    """POST a release_ready AdaptiveCard to the Teams workflow webhook.

    Returns True if sent (or attempted), False if skipped (no URL configured).
    Never raises — failures are logged at warning level so the RAB state
    transition still commits.
    """
    settings = get_settings()
    # Prefer the experiment's variable, fall back to legacy TEAMS_WEBHOOK_URL for backwards compat
    webhook_url = settings.TEAMS_WORKFLOW_WEBHOOK_URL or settings.TEAMS_WEBHOOK_URL  # type: ignore[attr-defined]
    if not webhook_url:
        logger.info("Teams release alert skipped for %s — TEAMS_WORKFLOW_WEBHOOK_URL not configured (alerting basis only)", issue_key)
        return False

    card = _build_release_card(issue_key, summary, details or {})
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(webhook_url, json=card, headers={"Content-Type": "application/json"})
            # Power Automate workflows often return 202 Accepted with empty body
            logger.info("Teams release alert for %s — HTTP %s", issue_key, resp.status_code)
            if resp.status_code >= 400:
                logger.warning("Teams alert for %s failed: HTTP %s body=%s", issue_key, resp.status_code, resp.text[:300])
                return False
            return True
    except Exception as e:  # httpx.RequestError etc.
        logger.warning("Teams release alert for %s failed: %s", issue_key, e)
        return False
