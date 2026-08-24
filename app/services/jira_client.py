"""Jira REST API client for fetching issues, comments, and transitions."""

import logging
import re
import asyncio
from typing import Any

import httpx

from app.config import get_settings

_DEFAULT_TIMEOUT = httpx.Timeout(30.0)
_MAX_RETRIES = 3
_RETRY_BACKOFF = 0.25

logger = logging.getLogger(__name__)

_ISSUE_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$")
_PROJECT_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]+$")


def _validate_issue_key(key: str) -> None:
    if not _ISSUE_KEY_RE.match(key):
        raise JiraClientError(f"Invalid issue key: {key}")


def _validate_project_key(key: str) -> None:
    if not _PROJECT_KEY_RE.match(key):
        raise JiraClientError(f"Invalid project key: {key}")


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
        return await self._request("GET", url, params=params)

    async def _put(self, path: str, body: dict) -> dict:
        if not self.base_url or not self.email or not self.api_token:
            raise JiraClientError("Jira configuration is incomplete.")
        url = f"{self.base_url.rstrip('/')}{path}"
        return await self._request("PUT", url, body=body)

    async def _post(self, path: str, body: dict) -> dict:
        if not self.base_url or not self.email or not self.api_token:
            raise JiraClientError("Jira configuration is incomplete.")
        url = f"{self.base_url.rstrip('/')}{path}"
        return await self._request("POST", url, body=body)

    async def _request(self, method: str, url: str, *, params: dict | None = None, body: dict | None = None) -> dict:
        """Perform a bounded retry for transient HTTP/network failures."""
        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                    resp = await client.request(
                        method, url, auth=self._auth(), headers=self._auth_headers(),
                        params=params, json=body,
                    )
                if resp.status_code == 429 or 500 <= resp.status_code < 600:
                    if attempt < _MAX_RETRIES:
                        retry_after = resp.headers.get("Retry-After")
                        delay = float(retry_after) if retry_after and retry_after.isdigit() else _RETRY_BACKOFF * (2 ** attempt)
                        await asyncio.sleep(min(delay, 5.0))
                        continue
                resp.raise_for_status()
                return resp.json() if resp.content else {}
            except httpx.RequestError as e:
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_BACKOFF * (2 ** attempt))
                    continue
                raise JiraClientError(f"Network error: {e}") from e
            except httpx.HTTPStatusError as e:
                raise JiraClientError(f"HTTP {e.response.status_code}: {e.response.text[:300]}") from e
        raise JiraClientError("Jira request failed after retries")

    async def get_issue(self, issue_key: str, fields: str | None = None) -> dict[str, Any]:
        _validate_issue_key(issue_key)
        params = {}
        if fields:
            params["fields"] = fields
        return await self._get(f"/rest/api/3/issue/{issue_key}", params=params)

    async def get_issue_comments(self, issue_key: str) -> list[dict]:
        _validate_issue_key(issue_key)
        data = await self._get(f"/rest/api/3/issue/{issue_key}/comment")
        return data.get("comments", [])

    async def add_comment(self, issue_key: str, body: str) -> dict:
        _validate_issue_key(issue_key)
        # Truncate to avoid Jira 400 on huge bodies
        if len(body) > 30000:
            body = body[:30000] + "… (truncated)"
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
        _validate_issue_key(issue_key)
        return await self._put(f"/rest/api/3/issue/{issue_key}", {"fields": fields})

    async def transition_issue(self, issue_key: str, transition_id: str) -> dict:
        _validate_issue_key(issue_key)
        return await self._post(f"/rest/api/3/issue/{issue_key}/transitions", {
            "transition": {"id": transition_id}
        })

    async def get_issue_remote_links(self, issue_key: str) -> list[dict]:
        _validate_issue_key(issue_key)
        data = await self._get(f"/rest/api/3/issue/{issue_key}/remotelink")
        return data if isinstance(data, list) else []

    async def search_issues(self, jql: str, max_results: int = 50, next_page_token: str | None = None) -> dict:
        """Search Jira issues via enhanced search (JQL). Handles pagination via nextPageToken."""
        params: dict[str, Any] = {"jql": jql, "maxResults": max_results}
        if next_page_token:
            params["nextPageToken"] = next_page_token
        # Try enhanced search POST first, fall back to GET /search
        try:
            return await self._post("/rest/api/3/search/jql", {"jql": jql, "maxResults": max_results, **({"nextPageToken": next_page_token} if next_page_token else {})})
        except JiraClientError:
            return await self._get("/rest/api/3/search", params=params)

    async def list_project_issues(self, project_key: str, max_results: int = 100) -> list[dict]:
        """Fetch all issues for a project, handling pagination."""
        _validate_project_key(project_key)
        all_issues: list[dict] = []
        next_token: str | None = None
        while True:
            data = await self.search_issues(f'project = "{project_key}" ORDER BY updated DESC', max_results=max_results, next_page_token=next_token)
            issues = data.get("issues", [])
            all_issues.extend(issues)
            next_token = data.get("nextPageToken")
            if not next_token or not issues:
                break
            if len(all_issues) >= 1000:  # safety cap
                break
        return all_issues

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
