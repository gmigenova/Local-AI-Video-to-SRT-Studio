"""Transcription job endpoints (section 10.5, 10.6)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import MODEL_CATALOG
from app.database.base import get_db
from app.models.job import JobStatus
from app.repositories.jobs import JobsRepository
from app.repositories.media import MediaRepository
from app.schemas.job import JobCreated, JobCreateRequest, JobOut
from app.workers.worker import _OPTION_KEYS, _RULE_KEYS

router = APIRouter()

_ALLOWED_SETTING_KEYS = _OPTION_KEYS | _RULE_KEYS


def _get_job_or_404(db: Session, job_id: str):
    job = JobsRepository(db).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@router.post("/jobs", response_model=JobCreated, status_code=201)
def create_job(payload: JobCreateRequest, db: Session = Depends(get_db)) -> JobCreated:
    if MediaRepository(db).get(payload.media_id) is None:
        raise HTTPException(status_code=404, detail="Media file not found.")
    if payload.model not in MODEL_CATALOG:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model '{payload.model}'. Available: {', '.join(MODEL_CATALOG)}",
        )
    unknown = set(payload.settings) - _ALLOWED_SETTING_KEYS
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported settings: {', '.join(sorted(unknown))}",
        )
    settings_json = {
        "model": payload.model,
        "language": payload.language,
        **{k: v for k, v in payload.settings.items() if v is not None},
    }
    job = JobsRepository(db).create(
        media_id=payload.media_id,
        model_name=payload.model,
        language=payload.language,
        settings_json=settings_json,
    )
    return JobCreated(job_id=job.id, status=job.status)


@router.get("/jobs")
def list_jobs(
    status: str | None = None,
    media_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> dict:
    repo = JobsRepository(db)
    jobs = repo.list_jobs(status=status, media_id=media_id, limit=limit, offset=offset)
    return {
        "items": [JobOut.model_validate(j) for j in jobs],
        "total": repo.count(status=status),
        "limit": limit,
        "offset": offset,
    }


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: Session = Depends(get_db)) -> JobOut:
    return JobOut.model_validate(_get_job_or_404(db, job_id))


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    _get_job_or_404(db, job_id)
    status = JobsRepository(db).request_cancel(job_id)
    return {"job_id": job_id, "status": status}


@router.post("/jobs/{job_id}/retry", response_model=JobOut)
def retry_job(job_id: str, db: Session = Depends(get_db)) -> JobOut:
    job = _get_job_or_404(db, job_id)
    if job.status not in (JobStatus.FAILED.value, JobStatus.CANCELLED.value):
        raise HTTPException(
            status_code=409,
            detail=f"Only failed or cancelled jobs can be retried (current: {job.status}).",
        )
    retried = JobsRepository(db).retry(job_id)
    assert retried is not None
    return JobOut.model_validate(retried)
