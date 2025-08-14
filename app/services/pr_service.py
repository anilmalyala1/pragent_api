import asyncio
from typing import List, Dict, Any
from app.core.github import GitHubClient
from app.model.schemas import PRItem
from app.utils.time import humanize_from_now

AI_LABELS = { "ai-reviewed", "ai_reviewed", "ai:reviewed" }

def _is_ai_reviewed(labels: List[Dict[str, Any]]) -> bool:
    for lb in labels or []:
        name = (lb.get("name") or "").casefold()
        if name in AI_LABELS:
            return True
    return False

class PRService:
    def __init__(self, gh: GitHubClient):
        self.gh = gh

    async def list_prs(self, owner: str, repos: List[str], state: str = "open") -> List[PRItem]:
        print("----"+owner)
        pr_lists = await asyncio.gather(*[self.gh.list_pull_requests(owner, r, state) for r in repos])

        async def build_item(repo: str, pr: Dict[str, Any]) -> PRItem:
            number = pr["number"]
            detail, files = await asyncio.gather(
                self.gh.get_pull_request(owner, repo, number),
                self.gh.list_pull_request_files(owner, repo, number),
            )
            return PRItem(
                id=str(number),  # use pr["id"] if you prefer the internal numeric ID
                title=pr.get("title") or "",
                author=(pr.get("user") or {}).get("login") or "",
                repo=repo,
                branch=(pr.get("head") or {}).get("ref") or "",
                commit=int(detail.get("commits") or 0),
                updatedAgo=humanize_from_now(pr.get("updated_at")),
                aiReviewed=_is_ai_reviewed(pr.get("labels") or []),
                files=files,
            )

        tasks = []
        for repo, prs in zip(repos, pr_lists):
            for pr in prs:
                tasks.append(build_item(repo, pr))

        items = await asyncio.gather(*tasks)
        # Sort by recency if desired (left as-is to preserve input order)
        return items
