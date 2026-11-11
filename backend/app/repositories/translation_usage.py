"""translation_usage repository: monthly Google Cloud Translation metering."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.translation_usage import TranslationUsage


def current_period(now: datetime | None = None) -> str:
    """Local calendar month key, ``YYYY-MM`` (matches Google's monthly quota)."""
    return (now or datetime.now()).strftime("%Y-%m")


class TranslationUsageRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, period: str) -> TranslationUsage | None:
        return self.db.scalars(
            select(TranslationUsage).where(TranslationUsage.period == period)
        ).first()

    def get_or_create(self, period: str) -> TranslationUsage:
        row = self.get(period)
        if row is None:
            row = TranslationUsage(period=period)
            self.db.add(row)
            # flush so a concurrent get_or_create on the same period hits the
            # unique index instead of silently creating a duplicate
            self.db.flush()
        return row

    def add_usage(
        self,
        period: str,
        *,
        characters: int,
        words: int,
        texts: int,
        requests: int,
    ) -> TranslationUsage:
        """Accumulate one translate operation into the monthly counter."""
        row = self.get_or_create(period)
        row.characters_sent += characters
        row.words_sent += words
        row.texts_translated += texts
        row.requests += requests
        row.jobs += 1
        self.db.commit()
        self.db.refresh(row)
        return row
