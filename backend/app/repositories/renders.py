"""video_renders repository (mirrors the jobs repository patterns §9)."""

from __future__ import annotations

import logging

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.common import utcnow
from app.models.render import ACTIVE_RENDER_STATUSES, RenderStatus, VideoRender

logger = logging.getLogger(__name__)

_ACTIVE_VALUES = [s.value for s in ACTIVE_RENDER_STATUSES]


class RendersRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # -- CRUD ----------------------------------------------------------
    def create(
        self, job_id: str, font_name: str | None = None, source: str = "editor"
    ) -> VideoRender:
        render = VideoRender(
            job_id=job_id,
            font_name=font_name,
            source=source,
            status=RenderStatus.QUEUED.value,
            current_stage="Queued",
        )
        self.db.add(render)
        self.db.commit()
        self.db.refresh(render)
        return render

    def get(self, render_id: str) -> VideoRender | None:
        return self.db.get(VideoRender, render_id)

    def latest_for_job(self, job_id: str) -> VideoRender | None:
        stmt = (
            select(VideoRender)
            .where(VideoRender.job_id == job_id)
            .order_by(VideoRender.created_at.desc(), VideoRender.id.desc())
            .limit(1)
        )
        return self.db.scalars(stmt).first()

    def active_for_job(self, job_id: str) -> VideoRender | None:
        stmt = (
            select(VideoRender)
            .where(
                VideoRender.job_id == job_id,
                VideoRender.status.in_(_ACTIVE_VALUES),
            )
            .order_by(VideoRender.created_at.desc())
            .limit(1)
        )
        return self.db.scalars(stmt).first()

    def count(self, status: str | None = None) -> int:
        stmt = select(func.count()).select_from(VideoRender)
        if status:
            stmt = stmt.where(VideoRender.status == status)
        return int(self.db.scalar(stmt) or 0)

    # -- claim ----------------------------------------------------------
    def claim_next(self) -> str | None:
        """Atomically claim the oldest queued render (UPDATE ... RETURNING)."""
        oldest_queued = (
            select(VideoRender.id)
            .where(VideoRender.status == RenderStatus.QUEUED.value)
            .order_by(VideoRender.created_at, VideoRender.id)
            .limit(1)
            .scalar_subquery()
        )
        stmt = (
            update(VideoRender)
            .where(
                VideoRender.id == oldest_queued,
                VideoRender.status == RenderStatus.QUEUED.value,
            )
            .values(
                status=RenderStatus.RUNNING.value,
                started_at=utcnow(),
                progress=0.0,
                current_stage="Preparing render",
                error_message=None,
            )
            .returning(VideoRender.id)
        )
        row = self.db.execute(stmt).first()
        self.db.commit()
        if row is None:
            return None
        logger.info("Claimed render %s", row[0])
        return str(row[0])

    # -- status updates --------------------------------------------------
    def update_status(
        self,
        render_id: str,
        status: RenderStatus,
        stage: str | None = None,
        error: str | None = None,
        progress: float | None = None,
        complete: bool = False,
        output_path: str | None = None,
        file_size: int | None = None,
    ) -> VideoRender | None:
        render = self.db.get(VideoRender, render_id)
        if render is None:
            return None
        render.status = status.value
        if stage is not None:
            render.current_stage = stage
        if error is not None:
            render.error_message = error
        if progress is not None:
            render.progress = progress
        if output_path is not None:
            render.output_path = output_path
        if file_size is not None:
            render.file_size = file_size
        if complete:
            render.completed_at = utcnow()
        self.db.commit()
        return render

    def set_progress(self, render_id: str, progress: float, stage: str) -> None:
        render = self.db.get(VideoRender, render_id)
        if render is None:
            return
        render.progress = round(max(0.0, min(progress, 100.0)), 1)
        render.current_stage = stage
        self.db.commit()

    # -- cancel ----------------------------------------------------------
    def request_cancel(self, render_id: str) -> str:
        """Move a render towards 'cancelled'. Returns the resulting status."""
        render = self.db.get(VideoRender, render_id)
        if render is None:
            raise LookupError(render_id)
        if render.status == RenderStatus.QUEUED.value:
            render.status = RenderStatus.CANCELLED.value
            render.completed_at = utcnow()
            render.current_stage = "Cancelled"
        elif render.status in _ACTIVE_VALUES:
            render.status = RenderStatus.CANCELLING.value
            render.current_stage = "Cancelling"
        result = render.status
        self.db.commit()
        return result

    # -- recovery ----------------------------------------------------------
    def recover_stale(self) -> int:
        """Requeue renders left mid-run by a dead render manager.

        Renders that were mid-cancel finish the cancel (the user's intent
        is clear); running ones go back to the queue and are re-rendered.
        """
        cancel_stmt = (
            update(VideoRender)
            .where(VideoRender.status == RenderStatus.CANCELLING.value)
            .values(
                status=RenderStatus.CANCELLED.value,
                completed_at=utcnow(),
                current_stage="Cancelled during restart",
            )
        )
        self.db.execute(cancel_stmt)
        stmt = (
            update(VideoRender)
            .where(VideoRender.status == RenderStatus.RUNNING.value)
            .values(
                status=RenderStatus.QUEUED.value,
                error_message=None,
                progress=0.0,
                current_stage="Requeued: restart recovery",
                started_at=None,
            )
        )
        result = self.db.execute(stmt)
        self.db.commit()
        recovered = int(getattr(result, "rowcount", 0) or 0)
        if recovered:
            logger.warning("Recovered %d stale render(s) after restart.", recovered)
        return recovered
