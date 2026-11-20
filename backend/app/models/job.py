"""ORM model + status enum: transcription_jobs (section 7.3, section 9)."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.common import new_id, utcnow

if TYPE_CHECKING:
    from app.models.job_settings import TranscriptionSettings
    from app.models.media_file import MediaFile
    from app.models.segment import TranscriptionSegment


class JobStatus(enum.Enum):
    """Job lifecycle states (section 7.3). Stored as lowercase strings."""

    QUEUED = "queued"
    VALIDATING = "validating"
    EXTRACTING_AUDIO = "extracting_audio"
    TRANSCRIBING = "transcribing"
    PROCESSING_SUBTITLES = "processing_subtitles"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"


#: statuses a worker may be actively running (excludes queued + terminal).
PROCESSING_JOB_STATUSES: tuple[JobStatus, ...] = (
    JobStatus.VALIDATING,
    JobStatus.EXTRACTING_AUDIO,
    JobStatus.TRANSCRIBING,
    JobStatus.PROCESSING_SUBTITLES,
)

#: everything that is not finished - requeued by restart recovery (section 9).
#: ``cancelling`` is deliberately excluded: recovery finishes the cancel
#: instead of requeueing, so it is handled before this set is applied.
ACTIVE_JOB_STATUSES: tuple[JobStatus, ...] = (JobStatus.QUEUED, *PROCESSING_JOB_STATUSES)


class TranscriptionJob(Base):
    __tablename__ = "transcription_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    media_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_files.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(30), default=JobStatus.QUEUED.value, index=True
    )
    model_name: Mapped[str] = mapped_column(String(100))
    language: Mapped[str | None] = mapped_column(String(20))
    detected_language: Mapped[str | None] = mapped_column(String(20))
    language_probability: Mapped[float | None] = mapped_column(Float)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    current_stage: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    media: Mapped[MediaFile] = relationship(back_populates="jobs")
    settings: Mapped[TranscriptionSettings | None] = relationship(
        back_populates="job",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    segments: Mapped[list[TranscriptionSegment]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TranscriptionSegment.segment_index",
    )

    # -- derived statistics (no columns; exposed via JobOut) --------------
    @property
    def processing_ms(self) -> int | None:
        """Wall time of the latest run (claim -> terminal state); None while
        queued/running or for a job cancelled before it started. Retry and
        restart recovery reset ``started_at``, so this never accumulates
        across runs."""
        if self.started_at is None or self.completed_at is None:
            return None
        delta = (self.completed_at - self.started_at).total_seconds() * 1000
        return int(delta) if delta >= 0 else None

    @property
    def media_duration_ms(self) -> int | None:
        """Duration of the source video (from the upload-time ffprobe probe)."""
        media = self.media
        return media.duration_ms if media is not None else None
