from typing import Dict, List, Optional
from app.core.github import GitHubClient
import re

class FileService:
    def __init__(self, gh: GitHubClient):
        self.gh = gh

    async def get_files_map(self, owner: str, repo: str, paths: List[str], ref: Optional[str] = None) -> Dict[str, str]:
        results: Dict[str, str] = {}
        for p in paths:
            content = await self.gh.get_file_text(owner, repo, p, ref=ref)
            results[p] = content
        return results

    async def get_pr_files_and_contents(
        self,
        owner: str,
        repo: str,
        number: int,
        paths: Optional[List[str]] = None,
    ):
        """
        - Reads PR detail to get head SHA.
        - If 'paths' is None, lists files from the PR.
        - Returns (headSha, files, {filename: content}) using contents?ref=headSha.
        """
        pr = await self.gh.get_pull_request(owner, repo, number)
        head = pr.get("head") or {}
        head_sha = head.get("sha") or ""

        if not head_sha:
            return {"headSha": "", "files": [], "contents": {}}

        files = paths or await self.gh.list_pull_request_files(owner, repo, number)
        contents = await self.get_files_map(owner, repo, files, ref=head_sha)
        return {"headSha": head_sha, "files": files, "contents": contents}


        # ---------- NEW: diff-aware helpers ----------
    HUNK_RE = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

    @classmethod
    def _changed_lines_from_patch(cls, patch: str) -> set[int]:
        """
        Parse unified diff 'patch' and return line numbers (new file side) that were added/modified.
        We mark:
          - Lines beginning with '+' (not '+++') within a hunk.
        """
        changed: set[int] = set()
        if not patch:
            return changed
        new_line = None
        for line in patch.splitlines():
            m = cls.HUNK_RE.match(line)
            if m:
                start = int(m.group(1))
                count = int(m.group(2) or "1")
                new_line = start
                continue
            if new_line is None:
                continue
            if line.startswith("+") and not line.startswith("+++"):
                changed.add(new_line)
                new_line += 1
            elif line.startswith("-") and not line.startswith("---"):
                # deletion on old file; do not advance new_line
                continue
            else:
                # context
                new_line += 1
        return changed

    async def get_pr_changed_lines(self, owner: str, repo: str, number: int) -> Dict[str, set[int]]:
        """
        Returns { filename: {changed_line_numbers...} } for the PR.
        """
        detailed = await self.gh.list_pull_request_files_detailed(owner, repo, number)
        out: Dict[str, set[int]] = {}
        for it in detailed:
            fn = it.get("filename")
            patch = it.get("patch") or ""
            out[fn] = self._changed_lines_from_patch(patch)
        return out