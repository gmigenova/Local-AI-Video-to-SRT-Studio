"""Storage retention / automatic cleanup (section 8, 19).

Cleanup rules — deliberately conservative:

- ``storage/temp/*``: removed after ``retention_temp_days`` (default 7).
- Extracted audio (``storage/audio/{job_id}``): removed for *completed*
  jobs after ``retention_audio_days`` (default 14). Derived data only —
  it can be re-extracted from the source video.
- Transcripts + exported subtitles: removed only when
  ``retention_artifacts_days`` > 0 (default 0 = keep forever, since these
  are user-facing output).
- Source videos (``storage/uploads/*``) are NEVER deleted by retention;
  deleting them requires an explicit project delete (user confirmation).

A setting of 0 days disables that rule (except temp, which defaults on).
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.models.job import JobStatus, TranscriptionJob

logger = logging.getLogger(__name__)

_DAY_SECONDS = 86_400


class RetentionService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------
    def cleanup_temp(self, now: float | None = None) -> int:
        """Delete expired entries under storage/temp. Returns removed count."""
        days = self.settings.retention_temp_days
        if days <= 0:
            return 0
        return self._cleanup_dir_age(self.settings.storage_subdir("temp"), days, now)

    def cleanup_audio(self, session: Session, now: float | None = None) -> int:
        """Delete extracted audio of completed jobs past retention."""
        days = self.settings.retention_audio_days
        if days <= 0:
            return 0
        return self._cleanup_completed_job_dirs(
            session, self.settings.storage_subdir("audio"), days, now
        )

    def cleanup_artifacts(self, session: Session, now: float | None = None) -> int:
        """Delete transcripts + subtitle exports of completed jobs past retention."""
        days = self.settings.retention_artifact_days
        if days <= 0:
            return 0
        removed = 0
        for sub in ("transcripts", "subtitles"):
            removed += self._cleanup_completed_job_dirs(
                session, self.settings.storage_subdir(sub), days, now
            )
        return removed

    def run_all(self, session_factory: sessionmaker[Session]) -> dict[str, int]:
        """Run every enabled rule; returns per-rule removed counts."""
        summary: dict[str, int] = {}
        summary["temp"] = self.cleanup_temp()
        session = session_factory()
        try:
            summary["audio"] = self.cleanup_audio(session)
            summary["artifacts"] = self.cleanup_artifacts(session)
        finally:
            session.close()
        total = sum(summary.values())
        if total:
            logger.info("Retention cleanup removed %d item(s): %s", total, summary)
        return summary

    # ------------------------------------------------------------------
    def _cleanup_dir_age(self, directory: Path, days: int, now: float | None) -> int:
        if not directory.is_dir():
            return 0
        cutoff = (now or time.time()) - days * _DAY_SECONDS
        removed = 0
        for entry in directory.iterdir():
            try:
                if entry.stat().st_mtime >= cutoff:
                    continue
                if entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink(missing_ok=True)
                removed += 1
            except OSError as exc:  # pragma: no cover - best effort
                logger.warning("Retention could not remove %s: %s", entry, exc)
        return removed

    def _cleanup_completed_job_dirs(
        self, session: Session, directory: Path, days: int, now: float | None
    ) -> int:
        """Remove {job_id} subdirectories of completed jobs past retention."""
        if not directory.is_dir():
            return 0
        cutoff = (now or time.time()) - days * _DAY_SECONDS
        completed_ids = set(
            session.scalars(
                select(TranscriptionJob.id).where(
                    TranscriptionJob.status == JobStatus.COMPLETED.value
                )
            )
        )
        removed = 0
        for entry in directory.iterdir():
            if not entry.is_dir() or entry.name not in completed_ids:
                continue  # never touch dirs of unknown/active jobs
            try:
                if entry.stat().st_mtime >= cutoff:
                    continue
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
            except OSError as exc:  # pragma: no cover - best effort
                logger.warning("Retention could not remove %s: %s", entry, exc)
        return removed
