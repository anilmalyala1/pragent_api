from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.github import get_github_client, GitHubClient
from app.services.pr_service import PRService
from app.model.schemas import PRItem, FileContent
from app.config import get_settings

router = APIRouter(prefix="/api/prs", tags=["PRs"])

@router.get("", response_model=List[PRItem])
async def get_prs(
    owner: str,
    repo: List[str] = Query(..., description="Repeat to query multiple repos, e.g. ?repo=one&repo=two"),
    state: str = Query("open", pattern=r"^(open|closed|all)$"),
    gh: GitHubClient = Depends(get_github_client),
):
    # Optional: enforce token presence for sane rate limits
    if not get_settings().github_token:
        raise HTTPException(status_code=400, detail="Set GITHUB_TOKEN for higher rate limits.")
    svc = PRService(gh)
    return await svc.list_prs(owner=owner, repos=repo, state=state)


@router.get("/{owner}/{repo}/{number}/contents", response_model=List[FileContent])
async def get_pr_contents(
    owner: str,
    repo: str,
    number: int,
    gh: GitHubClient = Depends(get_github_client),
):
    if not get_settings().github_token:
        raise HTTPException(status_code=400, detail="Set GITHUB_TOKEN for higher rate limits.")
    svc = PRService(gh)
    return await svc.get_pr_contents(owner, repo, number)
