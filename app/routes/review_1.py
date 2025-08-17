# app/api/routes/review.py
from typing import List, Optional
from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from app.agent.review_agent_sync import ReviewAgentSync, ReviewResult

router = APIRouter(prefix="/api/review", tags=["AI Review (Sync)"])

class ReviewRequestBody(BaseModel):
    paths: Optional[List[str]] = None
    only_changed: Optional[bool] = None
    include_static: Optional[bool] = None

@router.post("/{owner}/{repo}/{number}", response_model=ReviewResult)
def review_pull_request(owner: str, repo: str, number: int, body: ReviewRequestBody = Body(default=None)):
    try:
        agent = ReviewAgentSync()  # reads env: GITHUB_TOKEN, GOOGLE_API_KEY
        res = agent.review_pull_request(
            owner=owner,
            repo=repo,
            number=number,
            paths=(body.paths if body else None),
            only_changed=(body.only_changed if body else None),
            include_static=(body.include_static if body else None),
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Review failed: {e}")