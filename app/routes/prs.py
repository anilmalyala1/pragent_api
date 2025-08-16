from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.vcs_adapter import VCSAdapter
from app.core.adapter_factory import get_vcs_adapter
from app.services.pr_service import PRService
from app.model.schemas import PRItem
from app.config import get_settings

router = APIRouter(prefix="/api/prs", tags=["PRs"])

@router.get("", response_model=List[PRItem])
async def get_prs(
    owner: str,
    repo: List[str] = Query(..., description="Repeat to query multiple repos, e.g. ?repo=one&repo=two"),
    state: str = Query("open", pattern=r"^(open|closed|all)$"),
    vcs: VCSAdapter = Depends(get_vcs_adapter),
):
    # Optional: enforce token presence for sane rate limits
    if not get_settings().github_token:
        raise HTTPException(status_code=400, detail="Set GITHUB_TOKEN for higher rate limits.")
    svc = PRService(vcs)
    return await svc.list_prs(owner=owner, repos=repo, state=state)
