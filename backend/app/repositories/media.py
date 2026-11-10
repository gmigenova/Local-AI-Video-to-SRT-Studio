"""media_files repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.media_file import MediaFile


class MediaRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, **kwargs) -> MediaFile:
        media = MediaFile(**kwargs)
        self.db.add(media)
        self.db.commit()
        self.db.refresh(media)
        return media

    def get(self, media_id: str) -> MediaFile | None:
        return self.db.get(MediaFile, media_id)

    def list_for_project(self, project_id: str) -> list[MediaFile]:
        stmt = (
            select(MediaFile)
            .where(MediaFile.project_id == project_id)
            .order_by(MediaFile.created_at.desc())
        )
        return list(self.db.scalars(stmt))
