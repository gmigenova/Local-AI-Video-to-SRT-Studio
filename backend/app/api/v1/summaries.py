"""Video summary endpoints: LLM summary + key points from saved subtitles."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.base import get_db
from app.repositories.jobs import JobsRepository
from app.repositories.subtitles import SubtitlesRepository
from app.schemas.summary import SummarizeJobRequest, SummaryKeyPointOut, SummaryOut
from app.services.llm import SummaryServiceError, make_ollama_summarizer

router = APIRouter()

logger = logging.getLogger(__name__)

_SUMMARY_FILENAME = "summary.json"


def _get_job_or_404(db: Session, job_id: str):
    job = JobsRepository(db).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


def _summary_path(job_id: str):
    return get_settings().storage_subdir("transcripts") / job_id / _SUMMARY_FILENAME


@router.post("/jobs/{job_id}/summarize", response_model=SummaryOut)
def summarize_job(
    job_id: str,
    payload: SummarizeJobRequest,
    db: Session = Depends(get_db),
) -> SummaryOut:
    """Summarise the job's *saved* subtitle rows with a local Ollama model.

    The result is persisted as ``summary.json`` inside the job's transcripts
    directory (removed together with the job's other artifacts; governed by
    the same retention rule as transcripts). The subtitle rows themselves
    are never touched.
    """
    job = _get_job_or_404(db, job_id)
    rows = SubtitlesRepository(db).list_for_job(job_id)
    if not rows:
        raise HTTPException(status_code=409, detail="This job has no subtitles to summarise.")

    language = payload.language or (
        "th" if (job.detected_language or "").startswith("th") else "en"
    )
    summarizer = make_ollama_summarizer(get_settings(), model=payload.model)
    try:
        result = summarizer.summarize(
            [(row.start_ms, row.text) for row in rows], language
        )
    except SummaryServiceError as exc:
        logger.warning(
            "Ollama summary failed for job %s (%s): %s", job_id, language, exc.message
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    out = SummaryOut(
        job_id=job_id,
        model=summarizer.model_name,
        language=language,
        summary=result.summary,
        key_points=[
            SummaryKeyPointOut(time_ms=point.time_ms, text=point.text)
            for point in result.key_points
        ],
        cue_count=len(rows),
        generated_at=datetime.now(UTC),
    )

    path = _summary_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(out.model_dump_json(indent=2), encoding="utf-8")
    return out


@router.get("/jobs/{job_id}/summary", response_model=SummaryOut)
def get_job_summary(job_id: str, db: Session = Depends(get_db)) -> SummaryOut:
    """The previously generated summary (clean 404 until one exists)."""
    _get_job_or_404(db, job_id)
    path = _summary_path(job_id)
    if not path.is_file():
        raise HTTPException(
            status_code=404, detail="No summary has been generated for this job yet."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return SummaryOut.model_validate(data)
    except (OSError, ValueError) as exc:
        logger.warning("Stored summary for job %s is unreadable: %s", job_id, exc)
        raise HTTPException(
            status_code=404, detail="No summary has been generated for this job yet."
        ) from exc
