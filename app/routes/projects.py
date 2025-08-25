from typing import List
from fastapi import APIRouter, HTTPException

from app.model.schemas import Project
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["Projects"])

_service = ProjectService()

@router.get("", response_model=List[Project])
def list_projects() -> List[Project]:
    return _service.list_projects()


@router.get("/{project_id}", response_model=Project)
def get_project(project_id: str) -> Project:
    project = _service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("", response_model=Project)
def create_project(project: Project) -> Project:
    try:
        return _service.create_project(project)
    except ValueError:
        raise HTTPException(status_code=409, detail="Project already exists")


@router.put("/{project_id}", response_model=Project)
def update_project(project_id: str, project: Project) -> Project:
    updated = _service.update_project(project_id, project)
    if updated is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return updated


@router.delete("/{project_id}")
def delete_project(project_id: str) -> dict:
    if not _service.delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"detail": "Deleted"}
