"""Subtitle endpoints: list, update, bulk-update, reprocess, cleanup, export, import."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ExportError
from app.database.base import get_db
from app.repositories.jobs import JobsRepository
from app.repositories.subtitles import SubtitlesRepository
from app.schemas.cleanup import (
    CleanedTextItem,
    CleanupSubtitlesRequest,
    CleanupSubtitlesResponse,
)
from app.schemas.subtitle import (
    BulkSubtitleUpdate,
    SubtitleOut,
    SubtitleSyncRequest,
    SubtitleUpdate,
)
from app.services.diarization import (
    assign_speakers_to_subtitles,
    read_diarization_payload,
)
from app.services.export import ExportJobError, export_job_subtitles
from app.services.llm import CleanupServiceError, make_ollama_cleaner
from app.services.render import (
    MAX_SRT_BYTES,
    SrtImportError,
    decode_srt_bytes,
    parse_srt,
)
from app.services.subtitle import (
    ASSStyle,
    Subtitle,
    SubtitleProcessor,
    SubtitleRules,
    export_subtitles,
    rgb_to_ass_color,
)
from app.services.transcription.engine import make_segments_from_payload
from app.workers.worker import _RULE_KEYS

router = APIRouter()

logger = logging.getLogger(__name__)


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
                speaker=item.speaker,
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
                speaker=r.speaker,
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

    # re-apply speakers from the persisted diarization (transcripts are kept
    # forever), so reprocess does not silently drop the speaker labels
    turns = read_diarization_payload(
        get_settings().storage_subdir("transcripts") / job_id / "diarization.json"
    )
    labelled = 0
    if turns:
        labelled = assign_speakers_to_subtitles(result.subtitles, turns).apply_to(
            result.subtitles
        )

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
        "speakers": labelled,
    }


@router.post(
    "/jobs/{job_id}/subtitles/cleanup", response_model=CleanupSubtitlesResponse
)
def cleanup_job_subtitles(
    job_id: str,
    payload: CleanupSubtitlesRequest,
    db: Session = Depends(get_db),
) -> CleanupSubtitlesResponse:
    """Proofread the job's saved subtitle texts with a local Ollama model.

    Like the translate endpoint, this never persists anything: the cleaned
    texts are returned raw (aligned by 1-based index) and the editor applies
    them client-side as one undo step, letting auto-save persist them.
    Timestamps are never touched.
    """
    _get_job_or_404(db, job_id)
    rows = SubtitlesRepository(db).list_for_job(job_id)
    if not rows:
        raise HTTPException(status_code=409, detail="This job has no subtitles to clean up.")

    cleaner = make_ollama_cleaner(get_settings(), model=payload.model)
    try:
        result = cleaner.cleanup(texts=[row.text for row in rows], modes=payload.modes)
    except CleanupServiceError as exc:
        logger.warning(
            "Ollama cleanup failed for job %s (%s): %s",
            job_id,
            ",".join(payload.modes),
            exc.message,
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    cleaned = sum(1 for i, text in enumerate(result.texts) if text and text != rows[i].text)
    return CleanupSubtitlesResponse(
        job_id=job_id,
        model=cleaner.model_name,
        modes=payload.modes,
        cleaned=cleaned,
        total=len(rows),
        subtitles=[
            CleanedTextItem(index=i, text=text)
            for i, text in enumerate(result.texts, start=1)
        ],
    )


@router.post("/jobs/{job_id}/subtitles/import")
def import_subtitles(
    job_id: str,
    srt_file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict:
    """Replace the editable subtitles with an external ``.srt`` file.

    The imported cues become normal editor rows: previewed over the video,
    fully editable, auto-saved, exportable and burnable - exactly like the
    AI-transcribed ones. Multi-line cue text is preserved.
    """
    _get_job_or_404(db, job_id)
    if not (srt_file.filename or "").lower().endswith(".srt"):
        raise HTTPException(status_code=400, detail="Expected a .srt subtitle file.")
    data = srt_file.file.read(MAX_SRT_BYTES + 1)
    srt_file.file.close()
    try:
        cues = parse_srt(decode_srt_bytes(data))
    except SrtImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    repo = SubtitlesRepository(db)
    repo.replace_for_job(
        job_id,
        [
            Subtitle(
                index=i,
                start_ms=cue.start_ms,
                end_ms=cue.end_ms,
                text=cue.text,
                original_text=cue.text,
                is_edited=False,
            )
            for i, cue in enumerate(cues, start=1)
        ],
    )
    db.commit()

    # keep the on-disk SRT in sync with the imported subtitles
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

    return {"job_id": job_id, "subtitles": len(cues)}


@router.get("/jobs/{job_id}/export/{fmt}")
def export_subtitle_file(
    job_id: str,
    fmt: str,
    bom: bool = False,
    # prepend "[Speaker]" to labelled cues (srt/vtt/txt; needs diarization)
    speakers: bool = False,
    # ASS-only style overrides (ignored for other formats)
    font_name: str | None = None,
    font_size: int | None = None,
    primary_color: str | None = None,
    outline: float | None = None,
    margin_v: int | None = None,
    alignment: int | None = None,
    db: Session = Depends(get_db),
) -> FileResponse:
    style: ASSStyle | None = None
    if fmt.lower() == "ass":
        overrides: dict[str, object] = {}
        if font_name:
            overrides["font_name"] = font_name
        if font_size is not None:
            overrides["font_size"] = _clamp(font_size, 8, 200)
        if primary_color is not None:
            try:
                overrides["primary_color"] = rgb_to_ass_color(primary_color)
            except ExportError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        if outline is not None:
            overrides["outline"] = _clamp_float(outline, 0, 6)
        if margin_v is not None:
            overrides["margin_v"] = _clamp(margin_v, 0, 400)
        if alignment is not None:
            overrides["alignment"] = _clamp(alignment, 1, 9)
        style = ASSStyle(**overrides)  # type: ignore[arg-type]
    try:
        path, download_name, media_type = export_job_subtitles(
            db, job_id, fmt, utf8_bom=bom, style=style, prefix_speakers=speakers
        )
    except ExportJobError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return FileResponse(path, media_type=media_type, filename=download_name)


def _clamp(value: int | None, low: int, high: int) -> int | None:
    if value is None:
        return None
    return max(low, min(high, value))


def _clamp_float(value: float | None, low: float, high: float) -> float | None:
    if value is None:
        return None
    return max(low, min(high, value))
