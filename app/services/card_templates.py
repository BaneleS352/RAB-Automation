"""Adaptive Card templates for Teams notifications."""


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
