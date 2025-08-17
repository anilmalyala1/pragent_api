from typing import List
from app.core.vcs_adapter import VCSAdapter
from app.model.schemas import RepoItem

class RepoService:
    def __init__(self, vcs: VCSAdapter):
        self.vcs = vcs

    async def list_repos(self, owner: str) -> List[RepoItem]:
        repos = await self.vcs.list_repositories(owner)
        return [
            RepoItem(
                id=str(repo.get("id")),
                name=repo.get("name"),
                owner=owner,
                description=repo.get("description"),
                url=repo.get("html_url"),
            )
            for repo in repos
        ]
