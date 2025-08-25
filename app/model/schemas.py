from pydantic import BaseModel
from typing import List

class PRItem(BaseModel):
    id: str
    title: str
    author: str
    repo: str
    branch: str
    commit: int
    updatedAgo: str
    aiReviewed: bool
    files: List[str]


class Project(BaseModel):
    ProjectName: str
    ProjectId: str
