import csv
from pathlib import Path
from typing import List

from app.model.schemas import Project


class ProjectService:
    def __init__(self, csv_path: Path | None = None) -> None:
        if csv_path is None:
            csv_path = Path(__file__).resolve().parent.parent / "projects.csv"
        self.csv_path = csv_path
        self._projects: List[Project] = []
        self._load_projects()

    def _load_projects(self) -> None:
        if not self.csv_path.exists():
            return
        with self.csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row:
                    continue
                self._projects.append(
                    Project(
                        ProjectName=row.get("ProjectName", ""),
                        ProjectId=str(row.get("ProjectId", "")),
                        AccessToken=row.get("AccessToken", ""),
                    )
                )

    def list_projects(self) -> List[Project]:
        return self._projects

    def get_project(self, project_id: str) -> Project | None:
        return next((p for p in self._projects if p.ProjectId == project_id), None)

    def create_project(self, project: Project) -> Project:
        if self.get_project(project.ProjectId):
            raise ValueError("Project already exists")
        self._projects.append(project)
        return project

    def update_project(self, project_id: str, project: Project) -> Project | None:
        for idx, existing in enumerate(self._projects):
            if existing.ProjectId == project_id:
                self._projects[idx] = project
                return project
        return None

    def delete_project(self, project_id: str) -> bool:
        for idx, existing in enumerate(self._projects):
            if existing.ProjectId == project_id:
                del self._projects[idx]
                return True
        return False
