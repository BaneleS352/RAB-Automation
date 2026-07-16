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

    def _auth_headers(self) -> dict:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _auth(self) -> httpx.BasicAuth:
        return httpx.BasicAuth(self.email, self.api_token)

    async def _get(self, path: str, params: dict | None = None) -> dict:
        if not self.base_url or not self.email or not self.api_token:
            raise JiraClientError("Jira configuration is incomplete.")
        url = f"{self.base_url.rstrip('/')}{path}"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, auth=self._auth(), headers=self._auth_headers(), params=params)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            raise JiraClientError(f"HTTP {e.response.status_code}: {e.response.text[:300]}") from e
        except httpx.RequestError as e:
            raise JiraClientError(f"Network error: {e}") from e

    async def _put(self, path: str, body: dict) -> dict:
        if not self.base_url or not self.email or not self.api_token:
            raise JiraClientError("Jira configuration is incomplete.")
        url = f"{self.base_url.rstrip('/')}{path}"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.put(url, auth=self._auth(), headers=self._auth_headers(), json=body)
                resp.raise_for_status()
                return resp.json() if resp.content else {}
        except httpx.HTTPStatusError as e:
            raise JiraClientError(f"HTTP {e.response.status_code}: {e.response.text[:300]}") from e
        except httpx.RequestError as e:
            raise JiraClientError(f"Network error: {e}") from e

    async def _post(self, path: str, body: dict) -> dict:
        if not self.base_url or not self.email or not self.api_token:
            raise JiraClientError("Jira configuration is incomplete.")
        url = f"{self.base_url.rstrip('/')}{path}"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, auth=self._auth(), headers=self._auth_headers(), json=body)
                resp.raise_for_status()
                return resp.json() if resp.content else {}
        except httpx.HTTPStatusError as e:
            raise JiraClientError(f"HTTP {e.response.status_code}: {e.response.text[:300]}") from e
        except httpx.RequestError as e:
            raise JiraClientError(f"Network error: {e}") from e

    async def get_issue(self, issue_key: str, fields: str | None = None) -> Dict[str, Any]:
        params = {}
        if fields:
            params["fields"] = fields
        return await self._get(f"/rest/api/3/issue/{issue_key}", params=params)

    async def get_issue_comments(self, issue_key: str) -> list[dict]:
        data = await self._get(f"/rest/api/3/issue/{issue_key}/comment")
        return data.get("comments", [])

    async def add_comment(self, issue_key: str, body: str) -> dict:
        adf_body = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": body}],
                }
            ],
        }
        return await self._post(f"/rest/api/3/issue/{issue_key}/comment", {"body": adf_body})

    async def update_issue(self, issue_key: str, fields: dict) -> dict:
        return await self._put(f"/rest/api/3/issue/{issue_key}", {"fields": fields})

    async def transition_issue(self, issue_key: str, transition_id: str) -> dict:
        return await self._post(f"/rest/api/3/issue/{issue_key}/transitions", {
            "transition": {"id": transition_id}
        })

    async def get_issue_remote_links(self, issue_key: str) -> list[dict]:
        data = await self._get(f"/rest/api/3/issue/{issue_key}/remotelink")
        return data if isinstance(data, list) else []

    async def check_connection(self) -> dict:
        if not self.base_url or not self.email or not self.api_token:
            return {
                "connected": False,
                "details": "Jira API credentials or base URL are not configured.",
            }
        try:
            await self._get("/rest/api/3/myself")
            return {"connected": True, "details": "Jira API is reachable and authenticated."}
        except JiraClientError as e:
            return {"connected": False, "details": str(e)}
