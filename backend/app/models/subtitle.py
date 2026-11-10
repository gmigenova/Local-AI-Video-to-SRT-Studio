"""ORM model: subtitles (section 7.5).

The *editable* subtitle rows shown in the editor (section 11.5). ``text`` is
the user-facing current text; ``original_text`` keeps the AI output so
``is_edited`` / reprocess can always compare against it.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.common import new_id, utcnow


class SubtitleModel(Base):
    """DB row for one subtitle. (The editor-side domain object is
    ``app.services.subtitle.models.Subtitle``; this is its persisted form.)"""

    __tablename__ = "subtitles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transcription_jobs.id", ondelete="CASCADE"), index=True
    )
    subtitle_index: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(BigInteger)
    end_ms: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[str] = mapped_column(Text)
    original_text: Mapped[str] = mapped_column(Text)
    is_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )
