"""Speaker diarization via pyannote.audio (local-only, post-spec feature).

pyannote is an *optional* dependency (torch is heavy): it is imported lazily
inside :meth:`DiarizationService.load`, so the worker and the API stay
importable without it.  Availability (``is_available``) checks the config
flag, the HuggingFace token and the import - no network calls.

The pipeline runs on the job's extracted 16 kHz mono WAV after
transcription; the resulting speaker turns are aligned onto the subtitle
rows by :mod:`app.services.diarization.alignment` and persisted next to the
raw transcript as ``diarization.json`` (kept forever by retention), so
reprocess can re-apply speakers without re-running the model.

Heads-up on performance: speaker-diarization-3.1 on CPU takes a large
fraction of realtime (roughly 0.3-1x), so a 1 h video may add ~30-60 min
of processing. GPU needs WSL2/Docker - the same caveat as CTranslate2.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from app.core.config import Settings, get_settings
from app.core.errors import DiarizationError, DiarizationUnavailable

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiarizationTurn:
    """One contiguous stretch attributed to a single speaker."""

    start_ms: int
    end_ms: int
    speaker: str


class _PipelineLike(Protocol):
    """The slice of pyannote's Pipeline API we call (keeps mypy happy)."""

    def __call__(self, resource: Any, **kwargs: Any) -> Any: ...


class DiarizationService:
    """Wraps the pyannote pipeline behind a load-once, test-friendly API."""

    def __init__(
        self,
        settings: Settings | None = None,
        pipeline_factory: Callable[[Settings], _PipelineLike] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._pipeline_factory = pipeline_factory
        self._pipeline: _PipelineLike | None = None
        self._lock = threading.Lock()

    # -------------------------------------------------------------- status
    @staticmethod
    def is_available(settings: Settings | None = None) -> tuple[bool, str | None]:
        """(available, reason) - config + dependency check, no network."""
        cfg = settings or get_settings()
        if not cfg.diarize_enabled:
            return False, (
                "Speaker diarization is disabled. Set DIARIZE_ENABLED=true in .env "
                "and restart the backend."
            )
        if not cfg.huggingface_token:
            return False, (
                "Speaker diarization needs a HuggingFace token. Set HUGGINGFACE_TOKEN "
                "in .env and accept the model licenses at "
                "hf.co/pyannote/speaker-diarization-3.1 and hf.co/pyannote/segmentation-3.0."
            )
        try:
            import pyannote.audio  # noqa: F401
        except ImportError:
            return False, (
                "The pyannote dependency is not installed. "
                "Run: pip install -r backend/requirements-diarization.txt"
            )
        return True, None

    @property
    def model_name(self) -> str:
        return self._settings.diarize_model

    # ---------------------------------------------------------------- run
    def diarize(
        self,
        wav_path: Path,
        progress_callback: Callable[[float, str], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> list[DiarizationTurn]:
        """Run the pipeline on a 16 kHz mono WAV; returns speaker turns.

        Raises:
            DiarizationUnavailable: not configured / dependency missing.
            DiarizationError: the pipeline itself failed.
            OperationCancelled: ``cancel_event`` fired before the run started
                (pyannote's call is monolithic - cancellation is honoured
                between stages, not mid-run).
        """
        from app.core.errors import OperationCancelled

        if cancel_event is not None and cancel_event.is_set():
            raise OperationCancelled("Diarization cancelled before start.")

        pipeline = self._load()
        if progress_callback is not None:
            progress_callback(0.05, "Identifying speakers")
        try:
            annotation = pipeline(str(wav_path))
        except Exception as exc:  # noqa: BLE001 - third-party surface
            raise DiarizationError(f"Speaker diarization failed: {exc}") from exc
        if progress_callback is not None:
            progress_callback(1.0, "Identifying speakers")

        turns = [
            DiarizationTurn(
                start_ms=int(segment.start * 1000),
                end_ms=int(segment.end * 1000),
                speaker=str(speaker),
            )
            for segment, _, speaker in annotation.itertracks(yield_label=True)
        ]
        logger.info("Diarization produced %d speaker turns.", len(turns))
        return turns

    def _load(self) -> _PipelineLike:
        with self._lock:
            if self._pipeline is not None:
                return self._pipeline
            # a factory (test double) stands in for the real dependency and
            # bypasses the availability probe
            if self._pipeline_factory is not None:
                self._pipeline = self._pipeline_factory(self._settings)
                return self._pipeline
            available, reason = self.is_available(self._settings)
            if not available:
                raise DiarizationUnavailable(reason or "Diarization is not available.")
            try:
                from pyannote.audio import Pipeline
            except ImportError as exc:
                raise DiarizationUnavailable(
                    "The pyannote dependency is not installed. "
                    "Run: pip install -r backend/requirements-diarization.txt"
                ) from exc
            try:
                pipeline = Pipeline.from_pretrained(
                    self._settings.diarize_model,
                    use_auth_token=self._settings.huggingface_token,
                )
                device = self._settings.diarize_device
                if device and device != "cpu":
                    pipeline.to(torch_device(device))
            except Exception as exc:  # noqa: BLE001 - third-party surface
                raise DiarizationError(
                    f"Could not load the diarization model '{self._settings.diarize_model}': "
                    f"{exc}. Check the token and that both model licenses are accepted."
                ) from exc
            self._pipeline = pipeline
            return pipeline


def torch_device(name: str) -> Any:
    """Resolve a torch device by name (imported lazily - torch is optional)."""
    import torch

    return torch.device(name)


def write_diarization_payload(turns: list[DiarizationTurn], path: Path) -> None:
    """Persist speaker turns next to the raw transcript (survives reprocess)."""
    payload = {
        "model": get_settings().diarize_model,
        "turns": [
            {"start_ms": t.start_ms, "end_ms": t.end_ms, "speaker": t.speaker}
            for t in turns
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_diarization_payload(path: Path) -> list[DiarizationTurn] | None:
    """Load persisted turns; None when the file is missing or unreadable."""
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [
            DiarizationTurn(
                start_ms=int(turn["start_ms"]),
                end_ms=int(turn["end_ms"]),
                speaker=str(turn["speaker"]),
            )
            for turn in payload.get("turns", [])
        ]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning("Could not read diarization payload: %s", exc)
        return None


def make_diarizer(settings: Settings | None = None) -> DiarizationService:
    """Service from settings (always constructible - availability is live)."""
    return DiarizationService(settings)
