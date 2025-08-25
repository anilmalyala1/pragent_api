from typing import List
from fastapi import APIRouter

from app.model.schemas import Project
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["Projects"])

_service = ProjectService()

@router.get("", response_model=List[Project])
def get_projects():
    return _service.list_projects()
