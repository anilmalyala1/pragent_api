# app/api/routes/review.py
from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel

from app.core.github import get_github_client, GitHubAdapter
from app.services.file_service import FileService
from app.agent.review_agent_1 import build_review_graph
from app.model.review import ReviewResult, Issue

router = APIRouter(prefix="/api/review", tags=["AI Review"])

class ReviewRequestBody(BaseModel):
    thread_id:str=str(uuid.uuid4())
    paths: Optional[List[str]] = None
    only_changed: Optional[bool] = None       # default True (env)
    include_static: Optional[bool] = None     # default True (env)

@router.post("/{owner}/{repo}/{number}", response_model=ReviewResult)
async def review_pull_request(
    owner: str,
    repo: str,
    number: int,
    body: ReviewRequestBody = Body(default=None),
    gh: GitHubAdapter = Depends(get_github_client),
):
    file_svc = FileService(gh)
    app = build_review_graph(file_svc)

    state_in = {
        "owner": owner,
        "repo": repo,
        "number": number,
    }
    if body:
        if body.paths: state_in["paths"] = body.paths
        if body.only_changed is not None: state_in["only_changed"] = body.only_changed
        if body.include_static is not None: state_in["include_static"] = body.include_static

    try:
        config = {"configurable": {"thread_id": str(uuid.uuid4())}} 
        result = await app.ainvoke(state_in,config=config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Review failed: {e}")

    # Shape to UI contract
    issues = [Issue(**i) if not isinstance(i, Issue) else i for i in (result.get("issues") or [])]
    return ReviewResult(summary=result.get("summary", ""), issues=issues)