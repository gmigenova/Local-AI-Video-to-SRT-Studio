"""Shared helpers for the translation test modules (Google + Ollama).

Imported by test files after conftest.py has already redirected the
environment to the throwaway test database/storage tree.
"""

from __future__ import annotations

from app.database.base import get_session_factory
from app.models.media_file import MediaFile
from app.models.project import Project
from app.repositories.jobs import JobsRepository
from app.repositories.subtitles import SubtitlesRepository
from app.services.subtitle.models import Subtitle


def seed_translation_job(
    texts: list[str], detected_language: str | None = None
) -> str:
    """Create a project + media + job + subtitle rows; returns the job id.

    ``detected_language`` simulates a job whose transcription finished and
    detected a language (drives the Ollama source-language fallback).
    """
    db = get_session_factory()()
    try:
        project = Project(name="Translation Test")
        db.add(project)
        db.flush()
        media = MediaFile(
            project_id=project.id,
            original_name="clip.mp4",
            stored_name="clip.mp4",
            file_path="clip.mp4",
        )
        db.add(media)
        db.flush()
        job = JobsRepository(db).create(
            media_id=media.id, model_name="tiny", language=None, settings_json={}
        )
        if detected_language:
            job.detected_language = detected_language
        SubtitlesRepository(db).replace_for_job(
            job.id,
            [
                Subtitle(
                    index=i,
                    start_ms=(i - 1) * 2000,
                    end_ms=(i - 1) * 2000 + 1500,
                    text=text,
                    original_text=text,
                )
                for i, text in enumerate(texts, start=1)
            ],
        )
        db.commit()
        return job.id
    finally:
        db.close()


def clear_subtitles(job_id: str) -> None:
    db = get_session_factory()()
    try:
        SubtitlesRepository(db).replace_for_job(job_id, [])
        db.commit()
    finally:
        db.close()
