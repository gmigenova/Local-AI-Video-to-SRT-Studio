"""Subtitle export service: DB rows -> downloadable files (§10.8, §12)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import ExportError
from app.models.job import TranscriptionJob
from app.repositories.jobs import JobsRepository
from app.repositories.subtitles import SubtitlesRepository
from app.services.subtitle import (
    ASSStyle,
    Subtitle,
    export_subtitles,
    supported_formats,
)


class ExportJobError(Exception):
    """Raised with an HTTP status + clean message."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def export_job_subtitles(
    db: Session,
    job_id: str,
    fmt: str,
    utf8_bom: bool = False,
    settings: Settings | None = None,
    style: ASSStyle | None = None,
    prefix_speakers: bool = False,
) -> tuple[Path, str, str]:
    """Export a job's current subtitles.

    Returns ``(file_path, download_name, media_type)``. ``style`` only
    applies to the ASS format (styled export); ``prefix_speakers`` prepends
    ``[Speaker]`` to labelled cues in plain-text formats.
    """
    if fmt.lower() not in supported_formats():
        raise ExportJobError(400, f"Unsupported format '{fmt}'.")
    job = JobsRepository(db).get(job_id)
    if job is None:
        raise ExportJobError(404, "Job not found.")
    rows = SubtitlesRepository(db).list_for_job(job_id)
    if not rows:
        raise ExportJobError(409, "This job has no subtitles to export yet.")

    cfg = settings or get_settings()
    subtitles = [
        Subtitle(
            index=row.subtitle_index,
            start_ms=row.start_ms,
            end_ms=row.end_ms,
            text=row.text,
            original_text=row.original_text,
            is_edited=row.is_edited,
            speaker=row.speaker,
        )
        for row in rows
    ]
    out_dir = cfg.storage_subdir("subtitles") / job_id
    path = out_dir / f"output.{fmt.lower()}"
    try:
        export_subtitles(
            subtitles, path, fmt.lower(), utf8_bom=utf8_bom, style=style,
            prefix_speakers=prefix_speakers,
        )
    except ExportError as exc:
        raise ExportJobError(500, str(exc)) from exc

    download_name = f"{job.media.file_name_stem}.{fmt.lower()}"
    media_types = {
        "srt": "application/x-subrip",
        "vtt": "text/vtt",
        "txt": "text/plain",
        "json": "application/json",
        "ass": "text/x-ssa",
    }
    return path, download_name, media_types[fmt.lower()]


def job_has_subtitles(db: Session, job_id: str) -> bool:
    return bool(SubtitlesRepository(db).list_for_job(job_id))


def get_job_or_none(db: Session, job_id: str) -> TranscriptionJob | None:
    return JobsRepository(db).get(job_id)
