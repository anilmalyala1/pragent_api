from pydantic import BaseModel
from typing import List, Dict

class PRItem(BaseModel):
    id: str
    title: str
    author: str
    repo: str
    branch: str
    headSha: str           # NEW
    commit: int
    updatedAgo: str
    aiReviewed: bool
    files: List[str]

class PRFilesWithContents(BaseModel):
    headSha: str
    files: List[str]
    contents: Dict[str, str]  # {filename: filecontents}

class RepoItem(BaseModel):
    id: str
    name: str
    owner: str
    description: str | None = None
    url: str
