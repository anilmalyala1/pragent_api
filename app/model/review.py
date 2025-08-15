# app/models/review.py
from typing import List, Optional
from pydantic import BaseModel, Field

class IssuePatch(BaseModel):
    before: str = Field(..., description="Original code snippet to replace")
    after: str  = Field(..., description="Suggested replacement snippet")

class Issue(BaseModel):
    id: str
    file: str
    line: Optional[int] = None
    title: str
    description: str
    severity: str = Field(..., pattern="^(critical|major|minor)$")
    category: str = Field(..., pattern="^(security|quality|performance|best_practice)$")
    patch: Optional[IssuePatch] = None

class ReviewResult(BaseModel):
    summary: str
    issues: List[Issue]