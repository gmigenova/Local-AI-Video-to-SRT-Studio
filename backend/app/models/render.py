"""ORM model + status enum: video_renders (subtitle burn-in renders).

A render takes a completed transcription job's *current* subtitle rows,
writes them to a temporary SRT, and re-encodes the original video with the
subtitles burned into the picture (hardsub). Renders are CPU-bound FFmpeg
work and never touch the AI worker (one loaded model / GPU concurrency
invariant is unaffected).
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, BigInteger, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.common import new_id, utcnow

if TYPE_CHECKING:
    from app.models.job import TranscriptionJob


class RenderStatus(enum.Enum):
    """Render lifecycle states. Stored as lowercase strings."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"


#: statuses a render manager may be actively working on.
ACTIVE_RENDER_STATUSES: tuple[RenderStatus, ...] = (
    RenderStatus.QUEUED,
    RenderStatus.RUNNING,
    RenderStatus.CANCELLING,
)


class VideoRender(Base):
    __tablename__ = "video_renders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transcription_jobs.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(30), default=RenderStatus.QUEUED.value, index=True
    )
    #: where the burned subtitles came from: "editor" (the job's current
    #: subtitle rows) or "external" (a user-supplied .srt file).
    source: Mapped[str] = mapped_column(String(20), default="editor")
    #: how the subtitles are burned: plain "srt" (subtitles filter) or a
    #: styled "ass" (ass filter; style lives in style_json)
    subtitle_format: Mapped[str] = mapped_column(String(10), default="srt")
    #: ASSStyle overrides for styled renders (font, size, colours, position)
    style_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    current_stage: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    font_name: Mapped[str | None] = mapped_column(String(100))
    #: internal path to storage/renders/{id}/output.mp4 - never exposed via API
    output_path: Mapped[str | None] = mapped_column(Text)
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    job: Mapped[TranscriptionJob] = relationship()
