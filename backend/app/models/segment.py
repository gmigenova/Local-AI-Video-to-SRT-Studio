"""ORM model: transcription_segments (section 7.4).

The immutable raw AI transcript (the "ground truth" the subtitle editor can
always reprocess from, section 6): subtitle formatting never overwrites these
rows. Word-level timings live inside ``raw_data``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Double, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.common import new_id

if TYPE_CHECKING:
    from app.models.job import TranscriptionJob


class TranscriptionSegment(Base):
    __tablename__ = "transcription_segments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transcription_jobs.id", ondelete="CASCADE"), index=True
    )
    segment_index: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(BigInteger)
    end_ms: Mapped[int] = mapped_column(BigInteger)
    original_text: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Double)
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)

    job: Mapped[TranscriptionJob] = relationship(back_populates="segments")
