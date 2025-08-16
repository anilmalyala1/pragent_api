from base64 import b64decode
import httpx
from typing import Any, Dict, List, Optional
from app.config import Settings, get_settings
import os

from app.core.vcs_adapter import VCSAdapter

class GitHubAdapter(VCSAdapter):
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
    
    # -------- NEW: get a single file's text (decodes base64) --------
    async def get_file_text(
        self,
        owner: str,
        repo: str,
        path: str,
        ref: Optional[str] = None,
    ) -> Optional[str]:
        """
        Returns decoded text. If file > settings.max_file_bytes, it is truncated and annotated.
        Binary files will be decoded with replacement.
        Returns None if file doesn't exist at the specified reference.
        """
        params = {"ref": ref} if ref else None
        try:
            r = await self._client.get(f"/repos/{owner}/{repo}/contents/{path}", params=params)
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # File doesn't exist at the specified reference
                print(f"DEBUG: File {path} not found in {owner}/{repo} at ref {ref}")
                return None
            raise  # Re-raise other HTTP errors
        
        data = r.json()
        print(f"DEBUG: GitHub API response for {path}: {data.keys() if isinstance(data, dict) else 'Not a dict'}")
        print(f"DEBUG: Full response data: {data}")

        # If a directory is requested, GitHub returns a list — treat as error
        if isinstance(data, list):
            raise httpx.HTTPStatusError(f"Path is a directory: {path}", request=r.request, response=r)

        encoding = data.get("encoding")
        content_b64 = data.get("content", "")
        print(f"DEBUG: Encoding: {encoding}, Content length: {len(content_b64) if content_b64 else 0}")
        print(f"DEBUG: Content preview: {content_b64[:100] if content_b64 else 'None'}...")

        raw = b""
        if encoding == "base64" and content_b64:
            # GitHub includes newlines in base64; b64decode handles them
            try:
                # Remove any newlines and whitespace that might cause issues
                clean_content = content_b64.replace('\n', '').replace('\r', '').strip()
                raw = b64decode(clean_content)
                print(f"DEBUG: Decoded base64 content length: {len(raw)}")
            except Exception as e:
                print(f"DEBUG: Base64 decode error: {e}")
                # Fallback: try to decode as UTF-8 directly
                raw = content_b64.encode("utf-8", errors="replace")
                print(f"DEBUG: Fallback to UTF-8 encoding, length: {len(raw)}")
        else:
            # Some endpoints may return raw content (rare for /contents)
            raw = (content_b64 or "").encode("utf-8", errors="replace")
            print(f"DEBUG: Raw content length: {len(raw)}")

        max_bytes = self.settings.max_file_bytes
        truncated = False
        if len(raw) > max_bytes:
            raw = raw[:max_bytes]
            truncated = True

        text = raw.decode("utf-8", errors="replace")
        if truncated:
            text += "\n\n[... truncated due to server limit ...]"
        
        print(f"DEBUG: Final text length: {len(text)}")
        return text

    async def list_pull_request_files_detailed(self, owner: str, repo: str, number: int) -> List[Dict[str, Any]]:
        """
        Returns PR files with rich metadata including unified diffs in 'patch'.
        Each item example fields:
          filename, status, additions, deletions, changes, blob_url, raw_url, contents_url, patch (optional)
        """
        return await self._paginate(f"/repos/{owner}/{repo}/pulls/{number}/files", {"per_page": 100})
    
# FastAPI dependency factory
async def get_github_client(settings: Settings = get_settings()):
    client = GitHubAdapter(settings)
    try:
        yield client
    finally:
        await client.aclose()
