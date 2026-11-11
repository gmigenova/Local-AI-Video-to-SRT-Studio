"""Project endpoints (section 10.3)."""

from __future__ import annotations

import shutil

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.base import get_db
from app.models.job import JobStatus
from app.models.project import Project
from app.repositories.projects import ProjectsRepository
from app.repositories.renders import RendersRepository
from app.schemas.project import ProjectCreate, ProjectOut

router = APIRouter()

#: statuses that mean the AI worker is on (or about to pick up) a job of
#: this project - deleting underneath it would fail mid-write.
_BUSY_JOB_STATUSES = {s.value for s in JobStatus} - {
    JobStatus.COMPLETED.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
}


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
    """Delete a project with all its data (explicit user confirmation, §8).

    Removes the DB rows (media, jobs, segments, subtitles, renders cascade)
    and every on-disk artifact: uploaded videos, extracted audio, raw
    transcripts, subtitle exports and hardsub render outputs.
    """
    project = _get_project_or_404(db, project_id)
    settings = get_settings()
    renders_repo = RendersRepository(db)

    jobs = [job for media in project.media_files for job in media.jobs]

    # ---- guards: never delete underneath running work --------------------
    busy = next((job for job in jobs if job.status in _BUSY_JOB_STATUSES), None)
    if busy is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "This project has a transcription job that is queued or running. "
                "Wait for it to finish or cancel it first."
            ),
        )
    if renders_repo.active_for_jobs([job.id for job in jobs]):
        raise HTTPException(
            status_code=409,
            detail="A burn-in render is running for this project. Cancel it first.",
        )

    # ---- on-disk cleanup --------------------------------------------------
    for media in project.media_files:
        shutil.rmtree(settings.storage_subdir("uploads") / media.id, ignore_errors=True)
        for job in media.jobs:
            for sub in ("audio", "transcripts", "subtitles"):
                shutil.rmtree(settings.storage_subdir(sub) / job.id, ignore_errors=True)
            for render in renders_repo.list_for_job(job.id):
                shutil.rmtree(settings.storage_subdir("renders") / render.id, ignore_errors=True)
    ProjectsRepository(db).delete(project)
