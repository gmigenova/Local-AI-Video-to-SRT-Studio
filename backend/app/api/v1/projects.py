"""Project endpoints (section 10.3)."""

from __future__ import annotations

import shutil

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.base import get_db
from app.models.project import Project
from app.repositories.projects import ProjectsRepository
from app.schemas.project import ProjectCreate, ProjectOut

router = APIRouter()


def _get_project_or_404(db: Session, project_id: str) -> Project:
    project = ProjectsRepository(db).get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> ProjectOut:
    project = ProjectsRepository(db).create(name=payload.name, description=payload.description)
    return ProjectOut.model_validate(project)


@router.get("", response_model=list[ProjectOut])
def list_projects(
    limit: int = 100, offset: int = 0, db: Session = Depends(get_db)
) -> list[ProjectOut]:
    projects = ProjectsRepository(db).list(limit=limit, offset=offset)
    return [ProjectOut.model_validate(p) for p in projects]


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)) -> ProjectOut:
    return ProjectOut.model_validate(_get_project_or_404(db, project_id))


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str, db: Session = Depends(get_db)) -> None:
    """Delete a project with all its data (explicit user confirmation, §8)."""
    project = _get_project_or_404(db, project_id)
    settings = get_settings()
    for media in project.media_files:
        shutil.rmtree(settings.storage_subdir("uploads") / media.id, ignore_errors=True)
        for job in media.jobs:
            for sub in ("audio", "transcripts", "subtitles"):
                shutil.rmtree(settings.storage_subdir(sub) / job.id, ignore_errors=True)
    ProjectsRepository(db).delete(project)
