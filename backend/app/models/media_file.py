"""ORM model: media_files (section 7.2).

The original video never changes after upload; ``file_path`` points into
``storage/uploads/{media_id}/`` (section 8). Internal paths are never exposed
through the API (section 16).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.common import new_id, utcnow

if TYPE_CHECKING:
    from app.models.job import TranscriptionJob
    from app.models.project import Project


class MediaFile(Base):
    __tablename__ = "media_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    original_name: Mapped[str] = mapped_column(String(500))
    stored_name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(Text)
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    video_codec: Mapped[str | None] = mapped_column(String(100))
    audio_codec: Mapped[str | None] = mapped_column(String(100))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    audio_stream_index: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="media_files")
    jobs: Mapped[list[TranscriptionJob]] = relationship(
        back_populates="media",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def file_name_stem(self) -> str:
        """Stem of the original filename, used for export download names."""
        return Path(self.original_name).stem
