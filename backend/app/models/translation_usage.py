"""ORM model: translation_usage (cumulative Google Cloud Translation usage).

Google meters the Translation API per **character** sent for translation,
with quotas/billing per calendar month - so usage is accumulated per local
month period (``YYYY-MM``) and the character count is the primary metric the
monthly limit is enforced against.  Word/text/request counts are stored for
display only.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.common import new_id, utcnow


class TranslationUsage(Base):
    __tablename__ = "translation_usage"
    __table_args__ = (Index("ix_translation_usage_period", "period", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    #: local calendar month, "YYYY-MM"
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    #: characters actually sent to the API (Google's billing unit)
    characters_sent: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: whitespace-separated word count of the sent texts (display only)
    words_sent: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: number of texts translated (non-empty cues)
    texts_translated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: number of HTTP requests made to Google
    requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: number of translate operations (dialog submissions)
    jobs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
