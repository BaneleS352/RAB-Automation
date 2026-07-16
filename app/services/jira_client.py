import logging
from typing import Any, Dict

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

class JiraClientError(Exception):
    """Raised when the Jira API request fails."""
    pass

class JiraClient:
    """Client for interacting with the Jira REST API."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = self.settings.JIRA_BASE_URL
        self.email = self.settings.JIRA_EMAIL
        self.api_token = self.settings.JIRA_API_TOKEN

    async def get_issue(self, issue_key: str) -> Dict[str, Any]:
        """Fetch issue details from Jira.
        
        Args:
            issue_key: The Jira issue key (e.g., 'ABC-123').
            
        Returns:
            A dictionary containing the issue data.
            
        Raises:
            JiraClientError: If the request fails or is not properly configured.
        """
        if not self.base_url or not self.email or not self.api_token:
            logger.error("Jira API credentials or base URL are not fully configured.")
            raise JiraClientError("Jira configuration is incomplete.")

        url = f"{self.base_url.rstrip('/')}/rest/api/3/issue/{issue_key}"
        auth = httpx.BasicAuth(self.email, self.api_token)
        headers = {
            "Accept": "application/json"
        }

        logger.info("Fetching Jira issue %s from %s", issue_key, url)
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, auth=auth, headers=headers)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error("Jira API error for issue %s: HTTP %s - %s", issue_key, e.response.status_code, e.response.text)
            raise JiraClientError(f"Failed to fetch issue {issue_key}: HTTP {e.response.status_code}") from e
        except httpx.RequestError as e:
            logger.error("Network error while fetching issue %s: %s", issue_key, e)
            raise JiraClientError(f"Network error while fetching issue {issue_key}") from e

    async def check_connection(self) -> dict:
        """Verify connectivity to the Jira API.

        Returns:
            A dict with 'connected' (bool) and 'details' (str).
        """
        if not self.base_url or not self.email or not self.api_token:
            return {
                "connected": False,
                "details": "Jira API credentials or base URL are not configured.",
            }

        url = f"{self.base_url.rstrip('/')}/rest/api/3/myself"
        auth = httpx.BasicAuth(self.email, self.api_token)
        headers = {"Accept": "application/json"}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, auth=auth, headers=headers, timeout=10)
                response.raise_for_status()
                return {"connected": True, "details": "Jira API is reachable and authenticated."}
        except httpx.HTTPStatusError as e:
            return {
                "connected": False,
                "details": f"Jira API returned HTTP {e.response.status_code}: {e.response.text[:200]}",
            }
        except httpx.RequestError as e:
            return {
                "connected": False,
                "details": f"Network error: {e}",
            }
