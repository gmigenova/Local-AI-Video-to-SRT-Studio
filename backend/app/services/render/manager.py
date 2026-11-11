"""Background render manager: drives burn-in renders from the queue table.

Renders are CPU-bound FFmpeg work, so they run on a single daemon thread
inside the API process - the AI worker (GPU / model invariants §3.3) is
never involved and transcription jobs keep flowing while a render runs.

Guarantees (mirroring the AI worker, §9):
- renders are claimed atomically from ``video_renders`` (queued -> running)
- one render at a time (single manager thread)
- cancellation via a 'cancelling' status + in-process event
- restart recovery: running renders are requeued at startup
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.errors import OperationCancelled, VideoToSrtError
from app.database.base import get_session_factory
from app.models.render import RenderStatus
from app.repositories.renders import RendersRepository
from app.repositories.subtitles import SubtitlesRepository
from app.services.render.burner import RENDER_SRT_NAME, SubtitleBurner
from app.services.subtitle import Subtitle, export_subtitles

logger = logging.getLogger(__name__)


class RenderManager:
    """Processes burn-in renders from the SQLite queue, one at a time."""

    def __init__(
        self,
        settings: Settings | None = None,
        session_factory: sessionmaker[Session] | None = None,
        burner: SubtitleBurner | None = None,
        poll_interval: float | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._session_factory = session_factory or get_session_factory()
        self._burner = burner or SubtitleBurner()
        self.poll_interval = poll_interval or 2.0
        self._stop = threading.Event()
        self._cancel_events: dict[str, threading.Event] = {}
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Spawn the background loop (idempotent)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self.run_forever, name="render-manager", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal shutdown. Mid-run renders are requeued for the next start."""
        self._stop.set()
        for event in self._cancel_events.values():
            event.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None

    def run_forever(self) -> None:
        db = self._session_factory()
        try:
            recovered = RendersRepository(db).recover_stale()
            if recovered:
                logger.warning("Requeued %d interrupted render(s).", recovered)
        finally:
            db.close()
        logger.info("Render manager started.")
        while not self._stop.is_set():
            render_id = self.process_once()
            if render_id is None:
                self._stop.wait(self.poll_interval)
        logger.info("Render manager stopped.")

    def process_once(self) -> str | None:
        """Claim and run a single queued render. Returns the render id or None."""
        db = self._session_factory()
        try:
            render_id = RendersRepository(db).claim_next()
        finally:
            db.close()
        if render_id is None:
            return None
        logger.info("Processing render %s", render_id)
        self._run_render(render_id)
        return render_id

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------
    def cancel(self, render_id: str) -> str:
        """Flag a render as cancelling and stop its FFmpeg process."""
        db = self._session_factory()
        try:
            status = RendersRepository(db).request_cancel(render_id)
        finally:
            db.close()
        event = self._cancel_events.get(render_id)
        if event is not None:
            event.set()
        return status

    # ------------------------------------------------------------------
    # Render execution
    # ------------------------------------------------------------------
    def _run_render(self, render_id: str) -> None:
        db = self._session_factory()
        try:
            repo = RendersRepository(db)
            render = repo.get(render_id)
            if render is None:
                logger.error("Claimed render %s vanished.", render_id)
                return
            job = render.job
            media = job.media
            rows = SubtitlesRepository(db).list_for_job(render.job_id)
            if not rows:
                repo.update_status(
                    render_id,
                    RenderStatus.FAILED,
                    stage="Failed",
                    error="This job has no subtitles to burn.",
                    complete=True,
                )
                return

            render_dir = self.settings.storage_subdir("renders") / render_id
            srt_path = render_dir / RENDER_SRT_NAME
            output_path = render_dir / "output.mp4"
            render_dir.mkdir(parents=True, exist_ok=True)
            try:
                export_subtitles(
                    [
                        Subtitle(
                            index=r.subtitle_index,
                            start_ms=r.start_ms,
                            end_ms=r.end_ms,
                            text=r.text,
                            original_text=r.original_text,
                            is_edited=r.is_edited,
                        )
                        for r in rows
                    ],
                    srt_path,
                    "srt",
                )
            except VideoToSrtError as exc:
                repo.update_status(
                    render_id,
                    RenderStatus.FAILED,
                    stage="Failed",
                    error=str(exc),
                    complete=True,
                )
                return

            cancel_event = threading.Event()
            self._cancel_events[render_id] = cancel_event

            def on_progress(fraction: float) -> None:
                with self._fresh_session() as progress_db:
                    current = RendersRepository(progress_db).get(render_id)
                    if (
                        current is not None
                        and current.status == RenderStatus.CANCELLING.value
                    ):
                        cancel_event.set()
                RendersRepository(self._fresh_session()).set_progress(
                    render_id, fraction * 100.0, "Burning subtitles"
                )

            try:
                result = self._burner.burn(
                    media.file_path,
                    srt_path,
                    output_path,
                    duration_ms=media.duration_ms,
                    font_name=render.font_name,
                    audio_codec=media.audio_codec,
                    cancel_event=cancel_event,
                    on_progress=on_progress,
                )
            except OperationCancelled:
                logger.info("Render %s cancelled by user.", render_id)
                if self._stop.is_set():
                    # server shutdown: leave it queued for the next start
                    repo.update_status(render_id, RenderStatus.QUEUED, stage="Requeued")
                else:
                    repo.update_status(
                        render_id,
                        RenderStatus.CANCELLED,
                        stage="Cancelled",
                        complete=True,
                    )
                return
            except VideoToSrtError as exc:
                logger.error("Render %s failed: %s", render_id, exc)
                repo.update_status(
                    render_id, RenderStatus.FAILED, stage="Failed",
                    error=str(exc), complete=True,
                )
                return
            except Exception:  # noqa: BLE001 - never kill the manager loop
                logger.exception("Render %s crashed unexpectedly.", render_id)
                repo.update_status(
                    render_id,
                    RenderStatus.FAILED,
                    stage="Failed",
                    error="Unexpected render error (see server logs).",
                    complete=True,
                )
                return
            finally:
                self._cancel_events.pop(render_id, None)

            repo.update_status(
                render_id,
                RenderStatus.COMPLETED,
                stage="Completed",
                progress=100.0,
                complete=True,
                output_path=str(result.output_path),
                file_size=result.file_size,
            )
            logger.info("Render %s completed (%d bytes).", render_id, result.file_size)
        finally:
            db.close()

    def _fresh_session(self) -> Session:
        return self._session_factory()


# ----------------------------------------------------------------------
# Module-level singleton (created by the API lifespan / tests)
# ----------------------------------------------------------------------
_manager: RenderManager | None = None
_manager_lock = threading.Lock()


def get_render_manager() -> RenderManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = RenderManager()
        return _manager


def set_render_manager(manager: RenderManager | None) -> None:
    """Replace the singleton (tests)."""
    global _manager
    with _manager_lock:
        _manager = manager


def output_download_name(media_original_name: str) -> str:
    stem = Path(media_original_name).stem
    return f"{stem}.subtitled.mp4"
