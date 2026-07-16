import logging
import re
from urllib.parse import urlparse

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class AzureDevOpsClientError(Exception):
    pass


PR_URL_PATTERNS = [
    re.compile(r"dev\.azure\.com/([^/]+)/([^/]+)/_git/([^/]+)/pullrequest/(\d+)", re.IGNORECASE),
    re.compile(r"([^/]+)\.visualstudio\.com/([^/]+)/_git/([^/]+)/pullrequest/(\d+)", re.IGNORECASE),
]


def parse_pr_url(url: str) -> dict | None:
    for pattern in PR_URL_PATTERNS:
        m = pattern.search(url)
        if m:
            return {"org": m.group(1), "project": m.group(2), "repo": m.group(3), "pr_id": int(m.group(4))}
    return None


class AzureDevOpsClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.org = self.settings.AZURE_DEVOPS_ORG
        self.project = self.settings.AZURE_DEVOPS_PROJECT
        self.repo_id = self.settings.AZURE_DEVOPS_REPO_ID
        self.pat = self.settings.AZURE_DEVOPS_PAT

    def _is_configured(self) -> bool:
        return bool(self.org and self.project and self.pat)

    def _auth_headers(self) -> dict:
        return {
            "Accept": "application/json",
        }

    def _auth(self) -> httpx.BasicAuth:
        return httpx.BasicAuth("", self.pat)

    def _base_url(self) -> str:
        return f"https://dev.azure.com/{self.org}/{self.project}/_apis"

    async def _get(self, path: str, params: dict | None = None) -> dict:
        if not self._is_configured():
            raise AzureDevOpsClientError("Azure DevOps is not configured.")
        url = f"{self._base_url()}{path}"
        merged_params = dict(params or {})
        merged_params.setdefault("api-version", "7.1")
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, auth=self._auth(), headers=self._auth_headers(), params=merged_params)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            raise AzureDevOpsClientError(f"HTTP {e.response.status_code}: {e.response.text[:300]}") from e
        except httpx.RequestError as e:
            raise AzureDevOpsClientError(f"Network error: {e}") from e

    async def check_connection(self) -> dict:
        if not self._is_configured():
            return {"connected": False, "details": "Azure DevOps is not configured."}
        try:
            await self._get("/git/repositories")
            return {"connected": True, "details": "Azure DevOps API is reachable and authenticated."}
        except AzureDevOpsClientError as e:
            return {"connected": False, "details": str(e)}

    async def list_repositories(self) -> list[dict]:
        data = await self._get("/git/repositories")
        return data.get("value", [])

    async def get_pull_request(self, pr_id: int, repo_id: str | None = None) -> dict:
        rid = repo_id or self.repo_id
        if not rid:
            raise AzureDevOpsClientError("No repository ID configured.")
        return await self._get(f"/git/repositories/{rid}/pullrequests/{pr_id}")

    async def get_pull_request_by_url(self, pr_url: str) -> dict:
        parsed = parse_pr_url(pr_url)
        if not parsed:
            raise AzureDevOpsClientError(f"Could not parse PR URL: {pr_url}")
        self.org = parsed["org"]
        self.project = parsed["project"]
        return await self._get(
            f"/git/repositories/{parsed['repo']}/pullrequests/{parsed['pr_id']}",
            params={"searchCriteria.status": "all"},
        )

    async def get_pipeline_run(self, pipeline_id: int, run_id: int) -> dict:
        return await self._get(f"/build/builds/{run_id}", params={"definitions": pipeline_id})

    async def get_pipeline_run_by_url(self, pipeline_url: str) -> dict:
        m = re.search(r"buildId=(\d+)", pipeline_url)
        if not m:
            raise AzureDevOpsClientError(f"Could not extract build ID from URL: {pipeline_url}")
        run_id = int(m.group(1))
        return await self._get(f"/build/builds/{run_id}")
