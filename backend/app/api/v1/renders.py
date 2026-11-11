"""Video render (subtitle burn-in) endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database.base import get_db
from app.models.job import JobStatus
from app.models.render import ACTIVE_RENDER_STATUSES, RenderStatus, VideoRender
from app.repositories.jobs import JobsRepository
from app.repositories.renders import RendersRepository
from app.repositories.subtitles import SubtitlesRepository
from app.schemas.render import RenderCreated, RenderCreateRequest, RenderOut
from app.services.render import get_render_manager

router = APIRouter()

_ACTIVE_VALUES = [s.value for s in ACTIVE_RENDER_STATUSES]


def _get_render_or_404(db: Session, render_id: str) -> VideoRender:
    render = RendersRepository(db).get(render_id)
    if render is None:
        raise HTTPException(status_code=404, detail="Render not found.")
    return render


@router.post("/jobs/{job_id}/render", response_model=RenderCreated, status_code=201)
def start_render(
    job_id: str,
    payload: RenderCreateRequest | None = None,
    db: Session = Depends(get_db),
) -> RenderCreated:
    """Queue a burn-in render of the job's current subtitles (§10.8)."""
    job = JobsRepository(db).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status != JobStatus.COMPLETED.value:
        raise HTTPException(
            status_code=409,
            detail=f"Only completed jobs can be rendered (current: {job.status}).",
        )
    if not SubtitlesRepository(db).list_for_job(job_id):
        raise HTTPException(
            status_code=409, detail="This job has no subtitles to burn yet."
        )
    active = RendersRepository(db).active_for_job(job_id)
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail=f"A render is already in progress for this job (status: {active.status}).",
        )

    body = payload or RenderCreateRequest()
    render = RendersRepository(db).create(job_id, font_name=body.font_name)
    get_render_manager().start()  # ensure the background loop is running
    return RenderCreated(render_id=render.id, status=render.status)


@router.get("/jobs/{job_id}/render", response_model=RenderOut)
def latest_render(job_id: str, db: Session = Depends(get_db)) -> RenderOut:
    """The most recent render for a job (for editor polling)."""
    if JobsRepository(db).get(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    render = RendersRepository(db).latest_for_job(job_id)
    if render is None:
        raise HTTPException(status_code=404, detail="No render for this job yet.")
    return RenderOut.model_validate(render)


@router.get("/renders/{render_id}", response_model=RenderOut)
def get_render(render_id: str, db: Session = Depends(get_db)) -> RenderOut:
    return RenderOut.model_validate(_get_render_or_404(db, render_id))


@router.post("/renders/{render_id}/cancel")
def cancel_render(render_id: str, db: Session = Depends(get_db)) -> dict:
    render = _get_render_or_404(db, render_id)
    if render.status not in _ACTIVE_VALUES:
        raise HTTPException(
            status_code=409,
            detail=f"Only queued or running renders can be cancelled (current: {render.status}).",
        )
    status = get_render_manager().cancel(render_id)
    return {"render_id": render_id, "status": status}


@router.get("/renders/{render_id}/download")
def download_render(render_id: str, db: Session = Depends(get_db)) -> FileResponse:
    render = _get_render_or_404(db, render_id)
    if render.status != RenderStatus.COMPLETED.value:
        raise HTTPException(
            status_code=409,
            detail=f"The video is not ready yet (status: {render.status}).",
        )
    path = render.output_path
    if not path:
        raise HTTPException(status_code=409, detail="No output file was recorded.")
    file = Path(path)
    if not file.is_file():
        raise HTTPException(
            status_code=410, detail="The rendered file is no longer available."
        )
    download_name = f"{render.job.media.file_name_stem}.subtitled.mp4"
    return FileResponse(file, media_type="video/mp4", filename=download_name)
