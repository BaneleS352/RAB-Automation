"""RAB Orchestrator – stub service for Jira event processing.

This class will be replaced with real orchestration logic in future phases
(Jira API calls, Azure DevOps PR creation, SharePoint updates, etc.).
"""

import logging

from app.services.jira_client import JiraClient, JiraClientError

logger = logging.getLogger(__name__)


class RabOrchestrator:
    """Orchestrates RAB processing for incoming Jira events."""

    def __init__(self) -> None:
        self.jira_client = JiraClient()

    async def handle_jira_event(
        self,
        issue_key: str,
        event_type: str | None,
        payload: dict,
    ) -> str:
        """Process a Jira webhook event.

        Args:
            issue_key: The Jira issue key (e.g. "ABC-123").
            event_type: The webhook event type (e.g. "jira:issue_created").
            payload: The full webhook payload as a dict.

        Returns:
            A string describing the processing result.
        """
        logger.info(
            "Orchestrator received event: issue_key=%s, event_type=%s",
            issue_key,
            event_type,
        )
        
        # Fetch the full issue data from Jira API
        try:
            issue_data = await self.jira_client.get_issue(issue_key)
            logger.info("Successfully fetched issue data for %s", issue_key)
            # You can access specific fields from issue_data if needed
            # summary = issue_data.get("fields", {}).get("summary", "No Summary")
        except JiraClientError as e:
            logger.error("Failed to fetch issue data for %s: %s", issue_key, e)
            return f"error_fetching_issue_data: {e}"

        # Stub – real logic will be added in later phases
        return "queued_for_processing"
