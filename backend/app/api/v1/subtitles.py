"""Subtitle endpoints: list, update, bulk-update, reprocess, export (§10.7, §10.8)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.base import get_db
from app.repositories.jobs import JobsRepository
from app.repositories.subtitles import SubtitlesRepository
from app.schemas.subtitle import (
    BulkSubtitleUpdate,
    SubtitleOut,
    SubtitleSyncRequest,
    SubtitleUpdate,
)
from app.services.export import ExportJobError, export_job_subtitles
from app.services.subtitle import (
    Subtitle,
    SubtitleProcessor,
    SubtitleRules,
    export_subtitles,
)
from app.services.transcription.engine import make_segments_from_payload
from app.workers.worker import _RULE_KEYS

router = APIRouter()


def _get_job_or_404(db: Session, job_id: str):
    job = JobsRepository(db).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


def _validate_times(start_ms: int | None, end_ms: int | None, current: dict) -> None:
    start = start_ms if start_ms is not None else current["start_ms"]
    end = end_ms if end_ms is not None else current["end_ms"]
    if end <= start or start < 0:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid timestamps: end ({end}) must be greater than start ({start}).",
        )


@router.get("/jobs/{job_id}/subtitles", response_model=list[SubtitleOut])
def list_subtitles(job_id: str, db: Session = Depends(get_db)) -> list[SubtitleOut]:
    _get_job_or_404(db, job_id)
    rows = SubtitlesRepository(db).list_for_job(job_id)
    return [SubtitleOut.model_validate(r) for r in rows]


@router.put("/jobs/{job_id}/subtitles/{subtitle_id}", response_model=SubtitleOut)
def update_subtitle(
    job_id: str,
    subtitle_id: str,
    payload: SubtitleUpdate,
    db: Session = Depends(get_db),
) -> SubtitleOut:
    _get_job_or_404(db, job_id)
    repo = SubtitlesRepository(db)
    row = repo.get(job_id, subtitle_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Subtitle not found.")
    _validate_times(
        payload.start_ms,
        payload.end_ms,
        {"start_ms": row.start_ms, "end_ms": row.end_ms},
    )
    updated = repo.apply_update(
        row, start_ms=payload.start_ms, end_ms=payload.end_ms, text=payload.text
    )
    return SubtitleOut.model_validate(updated)


@router.post("/jobs/{job_id}/subtitles/bulk-update")
def bulk_update_subtitles(
    job_id: str, payload: BulkSubtitleUpdate, db: Session = Depends(get_db)
) -> dict:
    _get_job_or_404(db, job_id)
    repo = SubtitlesRepository(db)
    updated = 0
    for item in payload.updates:
        row = repo.get(job_id, item.id)
        if row is None:
            continue
        _validate_times(
            item.start_ms,
            item.end_ms,
            {"start_ms": row.start_ms, "end_ms": row.end_ms},
        )
        repo.apply_update_no_commit(
            row, start_ms=item.start_ms, end_ms=item.end_ms, text=item.text
        )
        updated += 1
    db.commit()  # single transaction (§7.7)
    return {"job_id": job_id, "updated": updated}


@router.post("/jobs/{job_id}/subtitles/sync")
def sync_subtitles(
    job_id: str, payload: SubtitleSyncRequest, db: Session = Depends(get_db)
) -> dict:
    """Full-state save from the subtitle editor (§11.5 auto-save).

    Replaces all subtitle rows in one transaction, renumbering 1..N in the
    order received. Covers text/time edits, add, delete, split and merge.
    """
    _get_job_or_404(db, job_id)
    for item in payload.subtitles:
        if item.end_ms <= item.start_ms:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid timestamps: end ({item.end_ms}) must be greater "
                f"than start ({item.start_ms}).",
            )
    repo = SubtitlesRepository(db)
    repo.replace_for_job(
        job_id,
        [
            Subtitle(
                index=i,
                start_ms=item.start_ms,
                end_ms=item.end_ms,
                text=item.text,
                original_text=item.original_text or item.text,
                is_edited=item.is_edited,
            )
            for i, item in enumerate(payload.subtitles, start=1)
        ],
    )
    db.commit()

    # keep the on-disk SRT in sync with what the user sees
    rows = repo.list_for_job(job_id)
    srt_dir = get_settings().storage_subdir("subtitles") / job_id
    export_subtitles(
        [
            Subtitle(
                index=r.subtitle_index,
                start_ms=r.start_ms,
                end_ms=r.end_ms,
                text=r.text,
                original_text=r.original_text,
                is_edited=r.is_edited,
            )
            for r in rows
        ],
        srt_dir / "output.srt",
        "srt",
    )

    return {"job_id": job_id, "saved": len(payload.subtitles)}


@router.post("/jobs/{job_id}/subtitles/reprocess")
def reprocess_subtitles(job_id: str, db: Session = Depends(get_db)) -> dict:
    """Re-segment subtitles from the saved raw transcription.

    This never re-runs AI transcription (§10.7).
    """
    job = _get_job_or_404(db, job_id)
    segments = [seg for seg in job.segments]
    segments.sort(key=lambda s: s.segment_index)
    if not segments:
        raise HTTPException(
            status_code=409,
            detail="No raw transcription is stored for this job.",
        )
    raw_payloads = [seg.raw_data or {} for seg in segments]
    rebuilt = make_segments_from_payload(raw_payloads)

    settings_json = job.settings.settings_json if job.settings else {}
    rules_kwargs = {k: v for k, v in settings_json.items() if k in _RULE_KEYS}
    rules = SubtitleRules(**rules_kwargs) if rules_kwargs else None
    result = SubtitleProcessor(rules).process(rebuilt)

    repo = SubtitlesRepository(db)
    repo.replace_for_job(job_id, result.subtitles)
    db.commit()

    # keep the initial SRT file in sync with the regenerated subtitles
    srt_dir = get_settings().storage_subdir("subtitles") / job_id
    export_subtitles(result.subtitles, srt_dir / "output.srt", "srt")

    return {
        "job_id": job_id,
        "subtitles": len(result.subtitles),
        "warnings": len(result.warnings),
    }


@router.get("/jobs/{job_id}/export/{fmt}")
def export_subtitle_file(
    job_id: str,
    fmt: str,
    bom: bool = False,
    db: Session = Depends(get_db),
) -> FileResponse:
    try:
        path, download_name, media_type = export_job_subtitles(
            db, job_id, fmt, utf8_bom=bom
        )
    except ExportJobError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return FileResponse(path, media_type=media_type, filename=download_name)
