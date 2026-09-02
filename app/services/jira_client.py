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

_ISSUE_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")
_PROJECT_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]+$")


def _validate_issue_key(key: str) -> None:
    if not _ISSUE_KEY_RE.match(key):
        raise JiraClientError(f"Invalid issue key: {key}")


def _validate_project_key(key: str) -> None:
    if not _PROJECT_KEY_RE.match(key):
        raise JiraClientError(f"Invalid project key: {key}")


class JiraClientError(Exception):
    """Raised when the Jira API request fails."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


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
        # Reuse one client across retries to avoid opening a new TCP connection per attempt
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            for attempt in range(_MAX_RETRIES + 1):
                try:
                    resp = await client.request(
                        method, url, auth=self._auth(), headers=self._auth_headers(),
                        params=params, json=body,
                    )
                    if resp.status_code == 429 or 500 <= resp.status_code < 600:
                        if attempt < _MAX_RETRIES:
                            retry_after = resp.headers.get("Retry-After")
                            try:
                                delay = float(retry_after) if retry_after else _RETRY_BACKOFF * (2 ** attempt)
                            except (TypeError, ValueError):
                                delay = _RETRY_BACKOFF * (2 ** attempt)
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
                    raise JiraClientError(f"HTTP {e.response.status_code}: {e.response.text[:300]}", status_code=e.response.status_code) from e
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

    async def search_issues(self, jql: str, max_results: int = 50, next_page_token: str | None = None, fields: list[str] | None = None) -> dict:
        """Search Jira issues via enhanced search (JQL). Handles pagination via nextPageToken."""
        # Request all fields so callers receive summary/status/assignee and RAB details.
        # Without explicit fields the enhanced search only returns id.
        if fields is None:
            fields = ["*all"]
        params: dict[str, Any] = {"jql": jql, "maxResults": max_results}
        if next_page_token:
            params["nextPageToken"] = next_page_token
        # Try enhanced search POST first, fall back to GET /search on 404 only
        try:
            body: dict[str, Any] = {"jql": jql, "maxResults": max_results, "fields": fields}
            if next_page_token:
                body["nextPageToken"] = next_page_token
            return await self._post("/rest/api/3/search/jql", body)
        except JiraClientError as e:
            # Robust 404 detection via status_code, not string parsing (which breaks on localized messages)
            if getattr(e, "status_code", None) != 404 and "404" not in str(e):
                raise
            # Fallback: legacy GET /search uses startAt for pagination
            fallback_params: dict[str, Any] = {"jql": jql, "maxResults": max_results, "fields": ",".join(fields)}
            if next_page_token and next_page_token.isdigit():
                fallback_params["startAt"] = int(next_page_token)
            elif next_page_token:
                # nextPageToken from enhanced search is opaque — start from 0 and let caller handle
                logger.warning("Falling back to GET /search but nextPageToken is opaque (%s) — pagination may be incomplete", next_page_token)
            return await self._get("/rest/api/3/search", params=fallback_params)

    async def list_project_issues(self, project_key: str, max_results: int = 100) -> list[dict]:
        """Fetch all issues for a project, handling pagination (enhanced + legacy)."""
        _validate_project_key(project_key)
        all_issues: list[dict] = []
        next_token: str | None = None
        while True:
            data = await self.search_issues(f'project = "{project_key}" ORDER BY updated DESC', max_results=max_results, next_page_token=next_token)
            issues = data.get("issues", [])
            all_issues.extend(issues)
            if len(all_issues) >= 1000:  # safety cap
                logger.warning("list_project_issues hit safety cap 1000 for project %s — truncated", project_key)
                break
            # Enhanced search uses nextPageToken
            next_token = data.get("nextPageToken")
            if next_token:
                if not issues:
                    break
                continue
            # Legacy GET /search uses startAt/total
            total = data.get("total")
            start_at = data.get("startAt")
            if total is not None and start_at is not None:
                if start_at + len(issues) >= total or not issues:
                    break
                next_token = str(start_at + len(issues))
                continue
            # No pagination info — single page
            break
        return all_issues

    async def create_issue(self, project_key: str, summary: str, description: str | None = None, issuetype: str = "Task", labels: list[str] | None = None, priority: str | None = None, assignee_account_id: str | None = None, custom_fields: dict[str, Any] | None = None) -> dict:
        """Create a Jira issue, including configured custom fields when supplied."""
        _validate_project_key(project_key)
        # Build ADF description
        adf = None
        if description is not None:
            adf = {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": description}]}],
            }
        fields: dict[str, Any] = {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": {"name": issuetype},
        }
        if adf is not None:
            fields["description"] = adf
        if labels:
            fields["labels"] = labels
        if priority:
            fields["priority"] = {"name": priority}
        if assignee_account_id:
            fields["assignee"] = {"accountId": assignee_account_id}
        if custom_fields:
            fields.update({key: value for key, value in custom_fields.items() if value not in (None, "")})
        return await self._post("/rest/api/3/issue", {"fields": fields})

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
