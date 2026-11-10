"""ORM model: transcription_settings (section 7.6).

One row per job: the exact transcription options + subtitle rules the job
was created with, stored as JSON. ``reprocess`` rebuilds subtitles from
these without re-running AI transcription (section 10.7).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.common import new_id, utcnow

if TYPE_CHECKING:
    from app.models.job import TranscriptionJob


class TranscriptionSettings(Base):
    __tablename__ = "transcription_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transcription_jobs.id", ondelete="CASCADE"), unique=True
    )
    settings_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    job: Mapped[TranscriptionJob] = relationship(back_populates="settings")
