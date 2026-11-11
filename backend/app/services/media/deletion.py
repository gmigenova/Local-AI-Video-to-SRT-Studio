"""Media deletion: guards + on-disk cleanup shared by the media and project
delete endpoints.

Deleting one media file removes everything derived from it: its upload dir,
and per transcription job the extracted audio, raw transcript, subtitle
exports and hardsub render outputs.  DB rows cascade via FKs
(``media_files`` -> jobs -> segments/subtitles/settings/renders).

Deletion is rejected while any derived job is queued/running or a burn-in
render is active - deleting underneath running work would fail mid-write.
"""

from __future__ import annotations

import shutil

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.job import JobStatus
from app.models.media_file import MediaFile
from app.repositories.media import MediaRepository
from app.repositories.renders import RendersRepository

#: statuses that mean the AI worker is on (or about to pick up) a job of
#: this media - deleting underneath it would fail mid-write.
BUSY_JOB_STATUSES = {s.value for s in JobStatus} - {
    JobStatus.COMPLETED.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
}


class MediaDeletionRejected(Exception):
    """Raised with an HTTP status + clean message (no internals leaked)."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def assert_media_idle(
    media_list: list[MediaFile], renders_repo: RendersRepository, subject: str = "video"
) -> None:
    """Raise :class:`MediaDeletionRejected` while jobs/renders are active."""
    for media in media_list:
        for job in media.jobs:
            if job.status in BUSY_JOB_STATUSES:
                raise MediaDeletionRejected(
                    409,
                    f"This {subject} has a transcription job that is queued or running. "
                    "Wait for it to finish or cancel it first.",
                )
    if renders_repo.active_for_jobs([job.id for media in media_list for job in media.jobs]):
        raise MediaDeletionRejected(
            409, f"A burn-in render is running for this {subject}. Cancel it first."
        )


def remove_media_artifacts(
    media_list: list[MediaFile],
    renders_repo: RendersRepository,
    settings: Settings | None = None,
) -> None:
    """Best-effort removal of every on-disk artifact of the given media."""
    cfg = settings or get_settings()
    for media in media_list:
        shutil.rmtree(cfg.storage_subdir("uploads") / media.id, ignore_errors=True)
        for job in media.jobs:
            for sub in ("audio", "transcripts", "subtitles"):
                shutil.rmtree(cfg.storage_subdir(sub) / job.id, ignore_errors=True)
            for render in renders_repo.list_for_job(job.id):
                shutil.rmtree(cfg.storage_subdir("renders") / render.id, ignore_errors=True)


def delete_media_file(db: Session, media: MediaFile) -> None:
    """Delete ONE media file with all its artifacts (guarded, single commit)."""
    renders_repo = RendersRepository(db)
    assert_media_idle([media], renders_repo)
    remove_media_artifacts([media], renders_repo)
    MediaRepository(db).delete(media)
