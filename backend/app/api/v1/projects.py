"""Project endpoints (section 10.3)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.base import get_db
from app.models.project import Project
from app.repositories.projects import ProjectsRepository
from app.repositories.renders import RendersRepository
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.services.media.deletion import (
    MediaDeletionRejected,
    assert_media_idle,
    remove_media_artifacts,
)

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


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str, payload: ProjectUpdate, db: Session = Depends(get_db)
) -> ProjectOut:
    """Rename a project and/or edit its description (partial update)."""
    project = _get_project_or_404(db, project_id)
    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates:
        updates["name"] = updates["name"].strip()
        if not updates["name"]:
            raise HTTPException(status_code=400, detail="Project name cannot be empty.")
    updated = ProjectsRepository(db).update(project, **updates)
    return ProjectOut.model_validate(updated)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str, db: Session = Depends(get_db)) -> None:
    """Delete a project with all its data (explicit user confirmation, §8).

    Removes the DB rows (media, jobs, segments, subtitles, renders cascade)
    and every on-disk artifact: uploaded videos, extracted audio, raw
    transcripts, subtitle exports and hardsub render outputs.
    """
    project = _get_project_or_404(db, project_id)
    renders_repo = RendersRepository(db)

    # guards first across ALL media so nothing is half-deleted (§7.7)
    try:
        assert_media_idle(list(project.media_files), renders_repo, subject="project")
    except MediaDeletionRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    remove_media_artifacts(list(project.media_files), renders_repo)
    ProjectsRepository(db).delete(project)
