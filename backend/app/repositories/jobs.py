"""transcription_jobs repository, including the atomic job claim (§9)."""

from __future__ import annotations

import logging

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.common import utcnow
from app.models.job import ACTIVE_JOB_STATUSES, PROCESSING_JOB_STATUSES, JobStatus, TranscriptionJob
from app.models.job_settings import TranscriptionSettings

logger = logging.getLogger(__name__)

_ACTIVE_VALUES = [s.value for s in ACTIVE_JOB_STATUSES]
_PROCESSING_VALUES = [s.value for s in PROCESSING_JOB_STATUSES]


class JobsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # -- CRUD ----------------------------------------------------------
    def create(
        self,
        media_id: str,
        model_name: str,
        language: str | None,
        settings_json: dict,
    ) -> TranscriptionJob:
        job = TranscriptionJob(
            media_id=media_id,
            model_name=model_name,
            language=language,
            status=JobStatus.QUEUED.value,
        )
        self.db.add(job)
        self.db.flush()
        self.db.add(TranscriptionSettings(job_id=job.id, settings_json=settings_json))
        self.db.commit()
        self.db.refresh(job)
        return job

    def get(self, job_id: str) -> TranscriptionJob | None:
        return self.db.get(TranscriptionJob, job_id)

    def list_jobs(
        self,
        status: str | None = None,
        media_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TranscriptionJob]:
        stmt = select(TranscriptionJob).order_by(TranscriptionJob.created_at.desc())
        if status:
            stmt = stmt.where(TranscriptionJob.status == status)
        if media_id:
            stmt = stmt.where(TranscriptionJob.media_id == media_id)
        return list(self.db.scalars(stmt.limit(limit).offset(offset)))

    def count(self, status: str | None = None) -> int:
        stmt = select(func.count()).select_from(TranscriptionJob)
        if status:
            stmt = stmt.where(TranscriptionJob.status == status)
        return int(self.db.scalar(stmt) or 0)

    # -- claim (§9) ----------------------------------------------------
    def claim_next(self) -> str | None:
        """Atomically claim the oldest queued job (single UPDATE ... RETURNING)."""
        oldest_queued = (
            select(TranscriptionJob.id)
            .where(TranscriptionJob.status == JobStatus.QUEUED.value)
            .order_by(TranscriptionJob.created_at, TranscriptionJob.id)
            .limit(1)
            .scalar_subquery()
        )
        stmt = (
            update(TranscriptionJob)
            .where(
                TranscriptionJob.id == oldest_queued,
                TranscriptionJob.status == JobStatus.QUEUED.value,
            )
            .values(
                status=JobStatus.VALIDATING.value,
                started_at=utcnow(),
                progress=0.0,
                current_stage="Job claimed by worker",
                error_message=None,
            )
            .returning(TranscriptionJob.id)
        )
        row = self.db.execute(stmt).first()
        self.db.commit()
        if row is None:
            return None
        logger.info("Claimed job %s", row[0])
        return str(row[0])

    # -- status updates --------------------------------------------------
    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        stage: str | None = None,
        error: str | None = None,
        progress: float | None = None,
        complete: bool = False,
        detected_language: str | None = None,
        language_probability: float | None = None,
    ) -> TranscriptionJob | None:
        job = self.db.get(TranscriptionJob, job_id)
        if job is None:
            return None
        job.status = status.value
        if stage is not None:
            job.current_stage = stage
        if error is not None:
            job.error_message = error
        if progress is not None:
            job.progress = progress
        if detected_language is not None:
            job.detected_language = detected_language
        if language_probability is not None:
            job.language_probability = language_probability
        if complete:
            job.completed_at = utcnow()
        self.db.commit()
        return job

    def set_progress(
        self,
        job_id: str,
        progress: float,
        stage: str,
        status: JobStatus | None = None,
    ) -> None:
        job = self.db.get(TranscriptionJob, job_id)
        if job is None:
            return
        job.progress = round(max(0.0, min(progress, 100.0)), 1)
        job.current_stage = stage
        if status is not None:
            job.status = status.value
        self.db.commit()

    # -- cancel / retry ---------------------------------------------------
    def request_cancel(self, job_id: str) -> str:
        """Move a job towards 'cancelled'. Returns the resulting status."""
        job = self.db.get(TranscriptionJob, job_id)
        if job is None:
            raise LookupError(job_id)
        if job.status == JobStatus.QUEUED.value:
            job.status = JobStatus.CANCELLED.value
            job.completed_at = utcnow()
            job.current_stage = "Cancelled"
        elif job.status in _ACTIVE_VALUES or job.status == JobStatus.CANCELLING.value:
            job.status = JobStatus.CANCELLING.value
            job.current_stage = "Cancelling"
        result = job.status
        self.db.commit()
        return result

    def retry(self, job_id: str) -> TranscriptionJob | None:
        job = self.db.get(TranscriptionJob, job_id)
        if job is None:
            return None
        job.status = JobStatus.QUEUED.value
        job.error_message = None
        job.progress = 0.0
        job.current_stage = None
        job.started_at = None
        job.completed_at = None
        job.detected_language = None
        job.language_probability = None
        self.db.commit()
        return job

    # -- recovery (§9) ----------------------------------------------------
    def recover_stale_jobs(self) -> int:
        """Requeue jobs left in a processing state by a dead worker."""
        # jobs that were mid-cancel when the worker died: finish the cancel
        cancel_stmt = (
            update(TranscriptionJob)
            .where(TranscriptionJob.status == JobStatus.CANCELLING.value)
            .values(
                status=JobStatus.CANCELLED.value,
                completed_at=utcnow(),
                current_stage="Cancelled during worker restart",
            )
        )
        self.db.execute(cancel_stmt)
        # everything else that was mid-processing goes back to the queue
        stmt = (
            update(TranscriptionJob)
            .where(TranscriptionJob.status.in_(_ACTIVE_VALUES))
            .values(
                status=JobStatus.QUEUED.value,
                error_message=None,
                progress=0.0,
                current_stage="Requeued: worker restart recovery",
                started_at=None,
            )
        )
        result = self.db.execute(stmt)
        self.db.commit()
        recovered = int(getattr(result, "rowcount", 0) or 0)
        if recovered:
            logger.warning("Recovered %d stale job(s) after worker restart.", recovered)
        return recovered
