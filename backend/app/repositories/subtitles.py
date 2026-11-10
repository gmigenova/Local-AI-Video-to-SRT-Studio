"""subtitles repository: editable subtitle rows (§7.5, §10.7)."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.subtitle import SubtitleModel
from app.services.subtitle.models import Subtitle


class SubtitlesRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_for_job(self, job_id: str) -> list[SubtitleModel]:
        stmt = (
            select(SubtitleModel)
            .where(SubtitleModel.job_id == job_id)
            .order_by(SubtitleModel.subtitle_index)
        )
        return list(self.db.scalars(stmt))

    def get(self, job_id: str, subtitle_id: str) -> SubtitleModel | None:
        stmt = select(SubtitleModel).where(
            SubtitleModel.job_id == job_id, SubtitleModel.id == subtitle_id
        )
        return self.db.scalars(stmt).first()

    def apply_update(
        self,
        subtitle: SubtitleModel,
        start_ms: int | None = None,
        end_ms: int | None = None,
        text: str | None = None,
    ) -> SubtitleModel:
        if start_ms is not None:
            subtitle.start_ms = int(start_ms)
        if end_ms is not None:
            subtitle.end_ms = int(end_ms)
        if text is not None:
            subtitle.text = text
        subtitle.is_edited = True
        self.db.commit()
        self.db.refresh(subtitle)
        return subtitle

    def bulk_update(self, job_id: str, updates: Sequence[dict]) -> int:
        """Apply many updates in one transaction; returns updated count."""
        updated = 0
        for item in updates:
            subtitle = self.get(job_id, str(item.get("id")))
            if subtitle is None:
                continue
            self.apply_update_no_commit(
                subtitle,
                start_ms=item.get("start_ms"),
                end_ms=item.get("end_ms"),
                text=item.get("text"),
            )
            updated += 1
        self.db.commit()
        return updated

    def apply_update_no_commit(
        self,
        subtitle: SubtitleModel,
        start_ms: int | None = None,
        end_ms: int | None = None,
        text: str | None = None,
    ) -> None:
        if start_ms is not None:
            subtitle.start_ms = int(start_ms)
        if end_ms is not None:
            subtitle.end_ms = int(end_ms)
        if text is not None:
            subtitle.text = text
        subtitle.is_edited = True

    def replace_for_job(self, job_id: str, subtitles: Sequence[Subtitle]) -> list[SubtitleModel]:
        """Replace all subtitle rows for a job (used after AI run / reprocess).

        The caller is responsible for committing the surrounding transaction.
        """
        self.db.execute(delete(SubtitleModel).where(SubtitleModel.job_id == job_id))
        rows = [
            SubtitleModel(
                job_id=job_id,
                subtitle_index=sub.index,
                start_ms=sub.start_ms,
                end_ms=sub.end_ms,
                text=sub.text,
                original_text=sub.original_text,
                is_edited=sub.is_edited,
            )
            for sub in subtitles
        ]
        self.db.add_all(rows)
        return rows
