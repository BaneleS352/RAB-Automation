"""Adaptive Card templates - removed.

This module has been removed as the team is shifting to a different
issue management and monitoring platform.

All Teams Adaptive Card templates have been removed from the codebase.
"""


def validation_failed_card(issue_key: str, missing_fields: list[str]) -> dict:
    return {"type": "AdaptiveCard", "version": "1.4", "body": []}


def validation_passed_card(issue_key: str) -> dict:
    return {"type": "AdaptiveCard", "version": "1.4", "body": []}


def approval_request_card(
    issue_key: str,
    summary: str,
    approver_role: str,
    approval_id: str,
) -> dict:
    return {"type": "AdaptiveCard", "version": "1.4", "body": []}


def rejection_notification_card(
    issue_key: str,
    approver_role: str,
    reason: str | None = None,
) -> dict:
    return {"type": "AdaptiveCard", "version": "1.4", "body": []}


def meeting_decision_card(issue_key: str) -> dict:
    return {"type": "AdaptiveCard", "version": "1.4", "body": []}


def meeting_needed_card(issue_key: str) -> dict:
    return {"type": "AdaptiveCard", "version": "1.4", "body": []}


def release_ready_card(issue_key: str) -> dict:
    return {"type": "AdaptiveCard", "version": "1.4", "body": []}


def developer_notification_card(issue_key: str, missing_fields: list[str]) -> dict:
    return {"type": "AdaptiveCard", "version": "1.4", "body": []}


def to_message_card(card: dict, callback_url: str = "") -> dict:
    return {}