from typing import Any, Dict, List, Optional
import httpx
from app.core.vcs_adapter import VCSAdapter
from app.config import Settings

class BitbucketAdapter(VCSAdapter):
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=self.settings.bitbucket_api_base,
            auth=(
                self.settings.bitbucket_username,
                self.settings.bitbucket_app_password,
            )
            if self.settings.bitbucket_username and self.settings.bitbucket_app_password
            else None,
            timeout=self.settings.request_timeout,
        )

    async def aclose(self):
        await self._client.aclose()

    async def _paginate(self, url: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        next_url = url
        while next_url:
            r = await self._client.get(next_url, params=params)
            r.raise_for_status()
            data = r.json()
            results.extend(data.get("values", []))
            next_url = data.get("next")
            params = None  # Subsequent requests use the full URL from 'next'
        return results

    async def list_repositories(self, owner: str) -> List[Dict[str, Any]]:
        url = f"/repositories/{owner}"
        return await self._paginate(url)

    async def list_pull_requests(self, owner: str, repo: str, state: str = "open") -> List[Dict[str, Any]]:
        # TODO: Implement Bitbucket API call
        return []

    async def get_pull_request(self, owner: str, repo: str, number: int) -> Dict[str, Any]:
        # TODO: Implement Bitbucket API call
        return {}

    async def list_pull_request_files(self, owner: str, repo: str, number: int) -> List[str]:
        # TODO: Implement Bitbucket API call
        return []

    async def get_file_text(self, owner: str, repo: str, path: str, ref: Optional[str] = None) -> Optional[str]:
        # TODO: Implement Bitbucket API call
        return None
