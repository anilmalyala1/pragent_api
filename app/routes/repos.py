from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from app.core.vcs_adapter import VCSAdapter
from app.core.adapter_factory import get_vcs_adapter
from app.services.repo_service import RepoService
from app.model.schemas import RepoItem
from app.config import get_settings

router = APIRouter(prefix="/api/repos", tags=["Repos"])

@router.get("", response_model=List[RepoItem])
async def get_repos(
    owner: str = Query(..., description="The owner of the repositories to list."),
    vcs: VCSAdapter = Depends(get_vcs_adapter),
):
    if not get_settings().github_token:
        raise HTTPException(status_code=400, detail="Set GITHUB_TOKEN for higher rate limits.")
    svc = RepoService(vcs)
    return await svc.list_repos(owner=owner)
