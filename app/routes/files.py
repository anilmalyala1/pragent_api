from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.github import get_github_client, GitHubAdapter
from app.services.file_service import FileService
from app.config import get_settings
from app.model.schemas import PRFilesWithContents

router = APIRouter(prefix="/api/files", tags=["Files"])

@router.get("", response_model=Dict[str, str])
async def get_files(
    owner: str,
    repo: str,
    path: List[str] = Query(..., description="Repeat for multiple files, e.g. ?path=src/a.py&path=src/b.py"),
    ref: Optional[str] = Query(None, description="Optional branch/commit/sha (e.g., main)"),
    gh: GitHubAdapter = Depends(get_github_client),
):
    if not get_settings().github_token:
        raise HTTPException(status_code=400, detail="Set GITHUB_TOKEN for higher rate limits.")
    if not path:
        raise HTTPException(status_code=400, detail="Provide at least one 'path'.")
    svc = FileService(gh)
    return await svc.get_files_map(owner=owner, repo=repo, paths=path, ref=ref)

# NEW: pull-request-aware contents fetch (uses PR_HEAD_SHA)
@router.get("/prs/{owner}/{repo}/{number}/contents", response_model=PRFilesWithContents)
async def get_pr_files_contents(
    owner: str,
    repo: str,
    number: int,
    path: Optional[List[str]] = Query(None, description="If omitted, uses files from the PR diff"),
    gh: GitHubAdapter = Depends(get_github_client),
):
    if not get_settings().github_token:
        raise HTTPException(status_code=400, detail="Set GITHUB_TOKEN for higher rate limits.")
    svc = FileService(gh)
    data = await svc.get_pr_files_and_contents(owner=owner, repo=repo, number=number, paths=path)
    return data
