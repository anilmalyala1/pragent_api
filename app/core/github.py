import httpx
from typing import Any, Dict, List, Optional
from app.config import Settings, get_settings

class GitHubClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=self.settings.github_api_base,
            headers=self._headers(),
            timeout=self.settings.request_timeout,
        )

    def _headers(self) -> Dict[str, str]:
        h = {"Accept": "application/vnd.github+json"}
        if self.settings.github_token:
            h["Authorization"] = f"Bearer {self.settings.github_token}"
        return h

    async def aclose(self):
        await self._client.aclose()

    async def _paginate(self, url: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        params = dict(params or {})
        params.setdefault("per_page", self.settings.per_page)
        results: List[Dict[str, Any]] = []
        for page in range(1, self.settings.max_pages + 1):
            p = dict(params, page=page)
            r = await self._client.get(url, params=p)
            r.raise_for_status()
            chunk = r.json()
            if not chunk:
                break
            results.extend(chunk)
            if len(chunk) < p["per_page"]:
                break
        return results

    # -------- GitHub API wrappers --------
    async def list_pull_requests(self, owner: str, repo: str, state: str = "open") -> List[Dict[str, Any]]:
        url = f"/repos/{owner}/{repo}/pulls"
        return await self._paginate(url, {"state": state})

    async def get_pull_request(self, owner: str, repo: str, number: int) -> Dict[str, Any]:
        r = await self._client.get(f"/repos/{owner}/{repo}/pulls/{number}")
        r.raise_for_status()
        return r.json()

    async def list_pull_request_files(self, owner: str, repo: str, number: int) -> List[str]:
        items = await self._paginate(f"/repos/{owner}/{repo}/pulls/{number}/files", {"per_page": 100})
        return [i.get("filename", "") for i in items]


# FastAPI dependency factory
async def get_github_client(settings: Settings = get_settings()):
    client = GitHubClient(settings)
    try:
        yield client
    finally:
        await client.aclose()
