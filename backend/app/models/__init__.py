"""SQLAlchemy ORM models (section 7 schema).

Importing this package registers every mapping on the shared ``Base``
metadata (see ``app.database.base.init_database``), so ``create_all`` and
Alembic autogenerate see the full schema.
"""

from __future__ import annotations

from app.models.job import (
    ACTIVE_JOB_STATUSES,
    PROCESSING_JOB_STATUSES,
    JobStatus,
    TranscriptionJob,
)
from app.models.job_settings import TranscriptionSettings
from app.models.media_file import MediaFile
from app.models.project import Project
from app.models.render import ACTIVE_RENDER_STATUSES, RenderStatus, VideoRender
from app.models.segment import TranscriptionSegment
from app.models.subtitle import SubtitleModel
from app.models.translation_usage import TranslationUsage

__all__ = [
    "ACTIVE_JOB_STATUSES",
    "ACTIVE_RENDER_STATUSES",
    "PROCESSING_JOB_STATUSES",
    "JobStatus",
    "MediaFile",
    "Project",
    "RenderStatus",
    "SubtitleModel",
    "TranscriptionJob",
    "TranscriptionSegment",
    "TranscriptionSettings",
    "TranslationUsage",
    "VideoRender",
]
