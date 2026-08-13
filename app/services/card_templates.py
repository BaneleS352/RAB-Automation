"""Adaptive Card templates for Teams notifications."""

import json


def validation_failed_card(issue_key: str, missing_fields: list[str]) -> dict:
    return {
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "size": "Medium",
                "weight": "Bolder",
                "text": f"RAB Validation Failed: {issue_key}",
            },
            {
                "type": "TextBlock",
                "text": "The following required fields are missing or invalid:",
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [{"title": f, "value": "Missing"} for f in missing_fields],
            },
        ],
    }


def validation_passed_card(issue_key: str) -> dict:
    return {
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "size": "Medium",
                "weight": "Bolder",
                "text": f"RAB Validation Passed: {issue_key}",
            },
            {
                "type": "TextBlock",
                "text": "All required fields are present. Proceeding to approval.",
                "wrap": True,
            },
        ],
    }


def approval_request_card(
    issue_key: str,
    summary: str,
    approver_role: str,
    approval_id: str,
) -> dict:
    return {
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "size": "Large",
                "weight": "Bolder",
                "text": f"RAB Approval Request: {issue_key}",
            },
            {
                "type": "TextBlock",
                "text": f"**Role:** {approver_role}",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": f"**Summary:** {summary}",
                "wrap": True,
            },
            {"type": "TextBlock", "text": "Do you approve this release?", "wrap": True},
            {
                "type": "Input.Text",
                "id": "reason",
                "placeholder": "Reason (required for reject)",
                "isMultiline": True,
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Approve",
                "data": {"action": "approve", "approval_id": approval_id, "issue_key": issue_key},
            },
            {
                "type": "Action.Submit",
                "title": "Reject",
                "data": {"action": "reject", "approval_id": approval_id, "issue_key": issue_key},
            },
        ],
    }


def rejection_notification_card(
    issue_key: str,
    approver_role: str,
    reason: str | None = None,
) -> dict:
    return {
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "size": "Medium",
                "weight": "Bolder",
                "text": f"RAB Rejected: {issue_key}",
            },
            {
                "type": "TextBlock",
                "text": f"**Rejected by:** {approver_role}",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": f"**Reason:** {reason or 'No reason provided.'}",
                "wrap": True,
            },
        ],
    }


def meeting_decision_card(issue_key: str) -> dict:
    return {
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "size": "Medium",
                "weight": "Bolder",
                "text": f"Post-Approval Meeting: {issue_key}",
            },
            {
                "type": "TextBlock",
                "text": "Is a coordination meeting needed for this release?",
                "wrap": True,
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Yes, schedule meeting",
                "data": {"action": "meeting_yes", "issue_key": issue_key},
            },
            {
                "type": "Action.Submit",
                "title": "No meeting needed",
                "data": {"action": "meeting_no", "issue_key": issue_key},
            },
        ],
    }


def developer_notification_card(issue_key: str, missing_fields: list[str]) -> dict:
    return {
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "size": "Medium",
                "weight": "Bolder",
                "text": f"Action Required: {issue_key}",
            },
            {
                "type": "TextBlock",
                "text": "Your RAB ticket is missing required information.",
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [{"title": f, "value": "Missing"} for f in missing_fields],
            },
            {
                "type": "TextBlock",
                "text": "Please update the ticket in Jira and trigger re-check.",
                "wrap": True,
                "color": "Attention",
            },
        ],
    }


def to_message_card(card: dict, callback_url: str = "") -> dict:
    """Convert an AdaptiveCard into an Office 365 MessageCard for incoming webhooks.

    ``Action.Submit`` buttons become ``HttpPOST`` actions that POST back to
    ``callback_url``; ``Action.OpenUrl`` buttons become ``OpenUri`` actions.
    MessageCards do not support text inputs, so the in-card "reason" field is
    not carried over when delivering via webhook.
    """
    header_title = ""
    text_lines: list[str] = []
    for block in card.get("body", []):
        block_type = block.get("type", "")
        text = block.get("text", "")
        if block_type == "TextBlock" and text:
            if not header_title and str(block.get("weight", "")).lower() == "bolder":
                header_title = text
            else:
                text_lines.append(text)
        elif block_type == "FactSet":
            text_lines.extend(
                f"**{fact.get('title', '')}:** {fact.get('value', '')}"
                for fact in block.get("facts", [])
            )

    actions: list[dict] = []
    if callback_url:
        for action in card.get("actions", []):
            action_type = action.get("type", "")
            if action_type == "Action.Submit":
                actions.append(
                    {
                        "@type": "HttpPOST",
                        "name": action.get("title", "Submit"),
                        "target": callback_url,
                        "body": json.dumps(action.get("data", {})),
                    }
                )
            elif action_type == "Action.OpenUrl":
                actions.append(
                    {
                        "@type": "OpenUri",
                        "name": action.get("title", "Open"),
                        "targets": [{"os": "default", "uri": action.get("url", "")}],
                    }
                )

    fallback = text_lines[0] if text_lines else "RAB Automation notification"
    message_card = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "summary": header_title or fallback,
        "title": header_title,
        "text": "\n\n".join(text_lines),
    }
    if actions:
        message_card["potentialAction"] = actions
    return message_card
