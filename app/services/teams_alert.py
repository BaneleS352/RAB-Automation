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
    actions: list[dict[str, str]] = []
    if settings.JIRA_BASE_URL:
        jira_link = f"{settings.JIRA_BASE_URL.rstrip('/')}/browse/{issue_key}"
        facts_seed = [{"title": "Jira link", "value": jira_link}]
        actions.append({"type": "Action.OpenUrl", "title": "View in Jira", "url": jira_link})
    else:
        # No Jira base URL configured — omit the link rather than sending a placeholder host
        facts_seed = []
    # Dashboard link: prefer the explicit public base URL; fall back to deriving
    # it from the webhook URL only when the expected path is present. Otherwise
    # omit (a relative path is useless inside Teams).
    if settings.APP_PUBLIC_URL:
        dashboard_link = f"{settings.APP_PUBLIC_URL.rstrip('/')}/dashboard/records/{issue_key}"
        actions.append({"type": "Action.OpenUrl", "title": "Open RAB dashboard", "url": dashboard_link})
    elif settings.JIRA_WEBHOOK_URL and "/webhooks/jira" in settings.JIRA_WEBHOOK_URL:
        dashboard_link = settings.JIRA_WEBHOOK_URL.replace("/webhooks/jira", f"/dashboard/records/{issue_key}")
        actions.append({"type": "Action.OpenUrl", "title": "Open RAB dashboard", "url": dashboard_link})

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
    facts.extend(facts_seed)

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
        "actions": actions,
    }


async def send_release_ready_alert(issue_key: str, summary: str = "", details: dict[str, Any] | None = None) -> bool:
    """POST a release_ready AdaptiveCard to the Teams workflow webhook.

    Returns True if sent (or attempted), False if skipped (no URL configured).
    Never raises — failures are logged at warning level so the RAB state
    transition still commits.
    """
    settings = get_settings()
    webhook_url = settings.effective_teams_webhook_url
    if not webhook_url:
        logger.info("Teams release alert skipped for %s — TEAMS_WORKFLOW_WEBHOOK_URL not configured (alerting basis only)", issue_key)
        return False

    card = _build_release_card(issue_key, summary, details or {})
    import asyncio as _asyncio

    # Bounded retry on rate-limit/transient failures, mirroring JiraClient backoff.
    # Never raises — failures are logged so the RAB state transition still commits.
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(webhook_url, json=card, headers={"Content-Type": "application/json"})
                # Power Automate workflows often return 202 Accepted with empty body
                logger.info("Teams release alert for %s — HTTP %s", issue_key, resp.status_code)
                if resp.status_code == 429 or 500 <= resp.status_code < 600:
                    if attempt < 2:
                        retry_after = resp.headers.get("Retry-After")
                        try:
                            delay = float(retry_after) if retry_after else 0.5 * (2 ** attempt)
                        except (TypeError, ValueError):
                            delay = 0.5 * (2 ** attempt)
                        await _asyncio.sleep(min(delay, 5.0))
                        continue
                    logger.warning("Teams alert for %s failed after retries: HTTP %s body=%s", issue_key, resp.status_code, resp.text[:300])
                    return False
                if resp.status_code >= 400:
                    logger.warning("Teams alert for %s failed: HTTP %s body=%s", issue_key, resp.status_code, resp.text[:300])
                    return False
                return True
        except Exception as e:  # httpx.RequestError etc.
            if attempt < 2:
                await _asyncio.sleep(0.5 * (2 ** attempt))
                continue
            logger.warning("Teams release alert for %s failed: %s", issue_key, e)
            return False
    return False
