"""Video render (subtitle burn-in) endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ExportError
from app.database.base import get_db
from app.models.job import JobStatus
from app.models.render import ACTIVE_RENDER_STATUSES, RenderStatus, VideoRender
from app.repositories.jobs import JobsRepository
from app.repositories.renders import RendersRepository
from app.repositories.subtitles import SubtitlesRepository
from app.schemas.render import RenderCreated, RenderOut
from app.services.render import (
    MAX_SRT_BYTES,
    SrtImportError,
    get_render_manager,
    normalise_srt,
)
from app.services.render.burner import RENDER_SRT_NAME
from app.services.subtitle import rgb_to_ass_color

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
    font_name: str | None = Form(None),
    srt_file: UploadFile | None = File(None),
    subtitle_format: str = Form("srt"),
    # ASS-only style overrides (ignored for plain SRT renders)
    font_size: int | None = Form(None),
    primary_color: str | None = Form(None),
    outline: float | None = Form(None),
    margin_v: int | None = Form(None),
    position: str | None = Form(None),
    db: Session = Depends(get_db),
) -> RenderCreated:
    """Queue a burn-in render.

    Without ``srt_file``: burns the job's current editor subtitles (the job
    must be completed and have subtitles). With ``srt_file``: burns the
    supplied external ``.srt`` instead - any job status is fine, the media
    file is all that matters.

    ``subtitle_format=ass`` renders a styled ASS (libass ``ass`` filter):
    the style comes from the optional ``font_name``/``font_size``/
    ``primary_color``/``outline``/``margin_v``/``position`` fields.
    """
    job = JobsRepository(db).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    if subtitle_format not in ("srt", "ass"):
        raise HTTPException(status_code=400, detail="subtitle_format must be 'srt' or 'ass'.")
    if subtitle_format == "ass" and srt_file is not None:
        raise HTTPException(
            status_code=400,
            detail="External subtitle files are only supported for plain SRT renders.",
        )

    style_json: dict | None = None
    if subtitle_format == "ass":
        style_json = {}
        if font_name:
            style_json["font_name"] = font_name
        if font_size is not None:
            style_json["font_size"] = max(8, min(200, font_size))
        if primary_color is not None:
            try:
                style_json["primary_color"] = rgb_to_ass_color(primary_color)
            except ExportError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        if outline is not None:
            style_json["outline"] = max(0.0, min(6.0, outline))
        if margin_v is not None:
            style_json["margin_v"] = max(0, min(400, margin_v))
        # numpad alignment: bottom-center 2, top-center 8, middle-center 5
        if position is not None:
            alignment = {"bottom": 2, "middle": 5, "top": 8}.get(position.lower())
            if alignment is None:
                raise HTTPException(
                    status_code=400, detail="position must be 'bottom', 'middle' or 'top'."
                )
            style_json["alignment"] = alignment
        if not style_json:
            style_json = None  # default style, nothing overridden

    external_text: str | None = None
    subtitle_count: int | None = None
    if srt_file is not None:
        if not (srt_file.filename or "").lower().endswith(".srt"):
            raise HTTPException(status_code=400, detail="Expected a .srt subtitle file.")
        data = srt_file.file.read(MAX_SRT_BYTES + 1)
        srt_file.file.close()
        try:
            external_text, subtitle_count = normalise_srt(data)
        except SrtImportError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        if job.status != JobStatus.COMPLETED.value:
            raise HTTPException(
                status_code=409,
                detail=f"Only completed jobs can be rendered (current: {job.status}). "
                "Attach an external .srt file to render without editor subtitles.",
            )
        subtitle_count = len(SubtitlesRepository(db).list_for_job(job_id))
        if subtitle_count == 0:
            raise HTTPException(
                status_code=409, detail="This job has no subtitles to burn yet."
            )

    active = RendersRepository(db).active_for_job(job_id)
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail=f"A render is already in progress for this job (status: {active.status}).",
        )

    source = "external" if external_text is not None else "editor"
    render = RendersRepository(db).create(
        job_id,
        font_name=font_name,
        source=source,
        subtitle_format=subtitle_format,
        style_json=style_json,
    )

    # stage the validated SRT for the manager to pick up
    if external_text is not None:
        render_dir = get_settings().storage_subdir("renders") / render.id
        render_dir.mkdir(parents=True, exist_ok=True)
        (render_dir / RENDER_SRT_NAME).write_text(external_text, encoding="utf-8")

    get_render_manager().start()  # ensure the background loop is running
    return RenderCreated(
        render_id=render.id,
        status=render.status,
        source=source,
        subtitle_count=subtitle_count,
    )


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
