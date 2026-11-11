"""AI background worker (section 9).

The AI process never runs inside an HTTP request: this standalone process
polls the SQLite job queue, atomically claims one queued job at a time, and
drives the transcription pipeline with live status updates.

Guarantees implemented here:
- only one worker claims a job (atomic UPDATE ... RETURNING, plus a lock file)
- one GPU job at a time (single worker = single pipeline = single model)
- job cancellation via a 'cancelling' status checked on every progress tick
- restart recovery: stale processing jobs are requeued at startup
- heartbeat file refreshed every poll / progress update
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from collections.abc import Callable

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.errors import OperationCancelled, VideoToSrtError
from app.core.logging_setup import configure_logging
from app.database.base import get_session_factory
from app.database.migrations import run_migrations
from app.models.job import JobStatus
from app.models.segment import TranscriptionSegment
from app.pipeline import PipelineResult, TranscriptionPipeline
from app.repositories.jobs import JobsRepository
from app.repositories.subtitles import SubtitlesRepository
from app.services.subtitle import SubtitleRules
from app.services.transcription import TranscriptionOptions
from app.workers import heartbeat

logger = logging.getLogger(__name__)

#: pipeline stage text prefix -> job status (§7.3)
_STAGE_STATUS: dict[str, JobStatus] = {
    "Validating": JobStatus.VALIDATING,
    "Extracting": JobStatus.EXTRACTING_AUDIO,
    "Loading model": JobStatus.TRANSCRIBING,
    "Transcribing": JobStatus.TRANSCRIBING,
    "Processing subtitles": JobStatus.PROCESSING_SUBTITLES,
    "Exporting": JobStatus.PROCESSING_SUBTITLES,
    "Completed": JobStatus.PROCESSING_SUBTITLES,
}

PipelineFactory = Callable[[], TranscriptionPipeline]

#: how often the worker runs storage retention cleanup
RETENTION_INTERVAL_SECONDS = 3600

_OPTION_KEYS = {
    "beam_size",
    "best_of",
    "temperature",
    "vad_filter",
    "word_timestamps",
    "condition_on_previous_text",
    "hallucination_silence_threshold",
    "initial_prompt",
    "vad_threshold",
    "vad_min_silence_ms",
}
_RULE_KEYS = set(SubtitleRules.model_fields)


def stage_to_status(stage: str | None) -> JobStatus | None:
    if not stage:
        return None
    for prefix, status in _STAGE_STATUS.items():
        if stage.startswith(prefix):
            return status
    return None


def options_from_settings(model_name: str, language: str | None, settings_json: dict):
    """Rebuild TranscriptionOptions + SubtitleRules from a job's stored config."""
    known = {k: v for k, v in (settings_json or {}).items() if v is not None}
    option_kwargs = {k: v for k, v in known.items() if k in _OPTION_KEYS}
    rules_kwargs = {k: v for k, v in known.items() if k in _RULE_KEYS}
    options = TranscriptionOptions(
        model=model_name, language=language, **option_kwargs  # type: ignore[arg-type]
    )
    rules = SubtitleRules(**rules_kwargs) if rules_kwargs else None
    return options, rules


class JobWorker:
    """Processes transcription jobs from the SQLite queue."""

    def __init__(
        self,
        settings: Settings | None = None,
        session_factory: sessionmaker[Session] | None = None,
        pipeline_factory: PipelineFactory | None = None,
        poll_interval: float | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._session_factory = session_factory or get_session_factory()
        self._pipeline_factory: PipelineFactory = pipeline_factory or (
            lambda: TranscriptionPipeline(settings=self.settings)
        )
        self.poll_interval = poll_interval or self.settings.worker_poll_interval
        self._stop = threading.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def run_forever(self) -> None:
        heartbeat.acquire_lock()
        try:
            recovered = JobsRepository(self._session_factory()).recover_stale_jobs()
            if recovered:
                logger.warning("Requeued %d interrupted job(s).", recovered)
            self._run_retention()
            heartbeat.write_heartbeat(None)
            logger.info("Worker started (pid=%s, poll=%.1fs).", _pid(), self.poll_interval)
            last_retention = time.monotonic()
            while not self._stop.is_set():
                job_id = self.process_once()
                if job_id is None:
                    self._stop.wait(self.poll_interval)
                    if time.monotonic() - last_retention > RETENTION_INTERVAL_SECONDS:
                        self._run_retention()
                        last_retention = time.monotonic()
                heartbeat.write_heartbeat(None)
        finally:
            heartbeat.release_lock()
            logger.info("Worker stopped.")

    def _run_retention(self) -> None:
        """Automatic storage cleanup (section 8/19). Never touches uploads."""
        try:
            from app.services.maintenance import RetentionService

            RetentionService(self.settings).run_all(self._session_factory)
        except Exception:  # noqa: BLE001 - cleanup must never kill the worker
            logger.exception("Retention cleanup failed.")

    def stop(self) -> None:
        self._stop.set()

    def process_once(self) -> str | None:
        """Claim and process a single job. Returns the job id or None."""
        factory = self._session_factory
        db = factory()
        try:
            job_id = JobsRepository(db).claim_next()
        finally:
            db.close()
        if job_id is None:
            return None
        logger.info("Processing job %s", job_id)
        self._process_job(job_id)
        return job_id

    # ------------------------------------------------------------------
    # Job processing
    # ------------------------------------------------------------------
    def _process_job(self, job_id: str) -> None:
        db = self._session_factory()
        try:
            jobs = JobsRepository(db)
            job = jobs.get(job_id)
            if job is None:
                logger.error("Claimed job %s vanished.", job_id)
                return
            media = job.media
            settings_json = job.settings.settings_json if job.settings else {}
            options, rules = options_from_settings(
                job.model_name, job.language, settings_json
            )

            cancel_event = threading.Event()
            audio_dir = self.settings.storage_subdir("audio") / job_id
            subtitles_dir = self.settings.storage_subdir("subtitles") / job_id
            transcripts_dir = self.settings.storage_subdir("transcripts") / job_id
            pipeline = self._pipeline_factory()

            def on_progress(fraction: float, stage: str) -> None:
                status = stage_to_status(stage)
                with self._fresh_session() as progress_db:
                    JobsRepository(progress_db).set_progress(
                        job_id, fraction * 100.0, stage, status=status
                    )
                    current = JobsRepository(progress_db).get(job_id)
                    if current is not None and current.status == JobStatus.CANCELLING.value:
                        cancel_event.set()
                heartbeat.write_heartbeat(job_id)

            try:
                result = pipeline.run(
                    video_path=media.file_path,
                    options=options,
                    rules=rules,
                    audio_stream_index=media.audio_stream_index,
                    work_dir=audio_dir,
                    output_dir=subtitles_dir,
                    export_formats=["srt"],
                    cancel_event=cancel_event,
                    progress=on_progress,
                )
            except OperationCancelled:
                logger.info("Job %s cancelled by user.", job_id)
                jobs.update_status(
                    job_id, JobStatus.CANCELLED, stage="Cancelled", complete=True
                )
                return
            except VideoToSrtError as exc:
                logger.error("Job %s failed: %s", job_id, exc)
                jobs.update_status(
                    job_id, JobStatus.FAILED, error=str(exc), stage="Failed", complete=True
                )
                return
            except Exception:  # noqa: BLE001 - never kill the worker loop
                logger.exception("Job %s crashed unexpectedly.", job_id)
                jobs.update_status(
                    job_id,
                    JobStatus.FAILED,
                    error="Unexpected processing error (see worker logs).",
                    stage="Failed",
                    complete=True,
                )
                return

            # Persist raw segments + subtitles in ONE transaction (§7.7).
            self._persist_results(db, job_id, result)

            # Keep the raw transcript in transcripts/{job_id}/ (§8).
            if result.transcript_path is not None and result.transcript_path.is_file():
                transcripts_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(
                    result.transcript_path, transcripts_dir / "transcript.json"
                )

            jobs.update_status(
                job_id,
                JobStatus.COMPLETED,
                stage="Completed",
                progress=100.0,
                complete=True,
                detected_language=result.language,
                language_probability=result.language_probability,
            )
            logger.info(
                "Job %s completed: %d subtitles, language=%s.",
                job_id, len(result.subtitles), result.language,
            )
        finally:
            db.close()

    def _persist_results(self, db: Session, job_id: str, result: PipelineResult) -> None:
        transcription = result.transcription
        if transcription is not None:
            for existing in db.query(TranscriptionSegment).filter_by(job_id=job_id):
                db.delete(existing)
            for index, seg in enumerate(transcription.segments):
                db.add(
                    TranscriptionSegment(
                        job_id=job_id,
                        segment_index=index,
                        start_ms=seg.start_ms,
                        end_ms=seg.end_ms,
                        original_text=seg.text,
                        confidence=seg.confidence,
                        raw_data={
                            "start_ms": seg.start_ms,
                            "end_ms": seg.end_ms,
                            "text": seg.text,
                            "words": [
                                {
                                    "start_ms": w.start_ms,
                                    "end_ms": w.end_ms,
                                    "word": w.word,
                                    "probability": w.probability,
                                }
                                for w in seg.words
                            ],
                        },
                    )
                )
        SubtitlesRepository(db).replace_for_job(job_id, result.subtitles)
        db.commit()

    def _fresh_session(self) -> Session:
        return self._session_factory()


def _pid() -> int:
    import os

    return os.getpid()


def main() -> int:
    configure_logging()
    settings = get_settings()
    settings.ensure_directories()
    run_migrations()
    worker = JobWorker(settings=settings)
    try:
        worker.run_forever()
    except KeyboardInterrupt:
        worker.stop()
        logger.info("Interrupted; exiting.")
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
