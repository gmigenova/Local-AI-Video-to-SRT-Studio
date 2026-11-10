"""Faster-Whisper implementation of :class:`TranscriptionEngine`.

Device strategy
---------------
The requested device (``auto`` / ``cuda`` / ``cpu``) is validated against the
*installed* CTranslate2 build before the model is loaded:

- CUDA-enabled CTranslate2 builds exist for Linux (native Windows builds are
  CPU-only).  Under WSL2/Docker with an NVIDIA GPU, ``cuda`` works normally.
- If CUDA is requested but unavailable, the engine logs a warning and falls
  back to CPU with an ``int8`` compute type so the application still works
  (albeit slower) instead of crashing.

Only parameters supported by the *installed* faster-whisper version are
forwarded to ``model.transcribe`` (section 3.4 of the specification).
"""

from __future__ import annotations

import inspect
import logging
from pathlib import Path
from threading import Event

from app.core.errors import ModelLoadError, OperationCancelled, TranscriptionError
from app.services.transcription.engine import (
    ProgressCallback,
    TranscribedSegment,
    TranscriptionEngine,
    TranscriptionOptions,
    TranscriptionResult,
    WordTiming,
    normalize_text,
)

logger = logging.getLogger(__name__)


def resolve_inference_target(device: str, compute_type: str) -> tuple[str, str, str | None]:
    """Validate the requested device/compute type against the installed runtime.

    Returns ``(effective_device, effective_compute_type, note)`` where
    ``note`` describes any fallback that was applied.
    """
    import ctranslate2

    try:
        cuda_device_count = ctranslate2.get_cuda_device_count()
    except Exception:  # pragma: no cover - defensive: very old ctranslate2
        cuda_device_count = 0

    note: str | None = None
    if device in ("auto", "cuda"):
        if cuda_device_count > 0:
            effective_device = "cuda"
        elif device == "cuda":
            effective_device = "cpu"
            note = (
                "CUDA was requested but this CTranslate2 build reports no CUDA "
                "devices (native Windows builds are CPU-only; use WSL2/Docker "
                "for GPU inference). Falling back to CPU."
            )
        else:
            effective_device = "cpu"
    elif device == "cpu":
        effective_device = "cpu"
    else:
        raise ModelLoadError(f"Unknown device '{device}'. Use auto, cuda or cpu.")

    if compute_type == "auto":
        effective_compute = "float16" if effective_device == "cuda" else "int8"
    else:
        effective_compute = compute_type

    return effective_device, effective_compute, note


class FasterWhisperEngine(TranscriptionEngine):
    """Speech-to-text engine backed by faster-whisper (CTranslate2)."""

    def __init__(
        self,
        model_name: str = "large-v3",
        device: str = "auto",
        compute_type: str = "auto",
        download_root: Path | str | None = None,
        num_workers: int = 1,
        cpu_threads: int = 8,
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._compute_type = compute_type
        self._download_root = str(download_root) if download_root else None
        self._num_workers = num_workers
        self._cpu_threads = cpu_threads
        self._model = None
        self._resolved_device: str | None = None

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def resolved_device(self) -> str | None:
        """Device actually in use after :meth:`load_model`."""
        return self._resolved_device

    def load_model(self) -> None:
        """Load the model once; subsequent calls are no-ops."""
        if self._model is not None:
            return
        from faster_whisper import WhisperModel

        device, compute_type, note = resolve_inference_target(
            self._device, self._compute_type
        )
        if note:
            logger.warning(note)
        logger.info(
            "Loading model '%s' on %s (compute_type=%s)...",
            self._model_name,
            device,
            compute_type,
        )
        try:
            self._model = WhisperModel(
                self._model_name,
                device=device,
                compute_type=compute_type,
                download_root=self._download_root,
                num_workers=self._num_workers,
                cpu_threads=self._cpu_threads,
            )
        except Exception as exc:
            raise ModelLoadError(
                f"Failed to load model '{self._model_name}' on {device}: {exc}"
            ) from exc
        self._resolved_device = device
        logger.info("Model '%s' loaded on %s.", self._model_name, device)

    def is_loaded(self) -> bool:
        return self._model is not None

    def _supported_transcribe_kwargs(self, options: TranscriptionOptions) -> dict:
        """Filter option kwargs down to those the installed version accepts."""
        assert self._model is not None
        candidate = options.to_engine_kwargs()
        supported = set(inspect.signature(self._model.transcribe).parameters)
        dropped = {
            k: v for k, v in candidate.items() if k not in supported and v is not None
        }
        if dropped:
            logger.warning(
                "Installed faster-whisper does not support options %s; they were ignored.",
                sorted(dropped),
            )
        return {k: v for k, v in candidate.items() if k in supported and v is not None}

    def transcribe(
        self,
        audio_path: Path | str,
        options: TranscriptionOptions,
        progress_callback: ProgressCallback | None = None,
        cancel_event: Event | None = None,
    ) -> TranscriptionResult:
        if self._model is None:
            raise TranscriptionError("Model is not loaded; call load_model() first.")

        kwargs = self._supported_transcribe_kwargs(options)
        logger.info(
            "Transcribing %s (language=%s, model=%s, kwargs=%s)",
            Path(audio_path).name,
            options.language or "auto",
            self._model_name,
            sorted(kwargs),
        )
        try:
            segments_iter, info = self._model.transcribe(str(audio_path), **kwargs)
        except Exception as exc:
            raise TranscriptionError(f"Transcription failed to start: {exc}") from exc

        total_seconds = float(info.duration or 0.0)
        collected: list[TranscribedSegment] = []

        try:
            for segment in segments_iter:  # generator: consumes lazily
                if cancel_event is not None and cancel_event.is_set():
                    raise OperationCancelled("Transcription cancelled by user.")
                words = tuple(
                    WordTiming(
                        start_ms=int(round(w.start * 1000)),
                        end_ms=int(round(w.end * 1000)),
                        word=w.word,
                        probability=getattr(w, "probability", None),
                    )
                    for w in (segment.words or ())
                )
                text = normalize_text(segment.text)
                if not text:
                    continue
                confidence: float | None = None
                if words:
                    probs = [w.probability for w in words if w.probability is not None]
                    if probs:
                        confidence = sum(probs) / len(probs)
                collected.append(
                    TranscribedSegment(
                        start_ms=int(round(segment.start * 1000)),
                        end_ms=int(round(segment.end * 1000)),
                        text=text,
                        words=words,
                        confidence=confidence,
                        raw={
                            "id": segment.id,
                            "seek": segment.seek,
                            "avg_logprob": segment.avg_logprob,
                            "compression_ratio": segment.compression_ratio,
                            "no_speech_prob": segment.no_speech_prob,
                            "temperature": segment.temperature,
                        },
                    )
                )
                if progress_callback is not None and total_seconds > 0:
                    fraction = min(segment.end / total_seconds, 0.999)
                    progress_callback(fraction, "Transcribing audio")
        except OperationCancelled:
            raise
        except Exception as exc:
            raise TranscriptionError(f"Transcription failed: {exc}") from exc

        logger.info(
            "Transcription finished: %d segments, language=%s (p=%.2f)",
            len(collected),
            info.language,
            info.language_probability or 0.0,
        )
        return TranscriptionResult(
            language=info.language,
            language_probability=info.language_probability,
            duration_ms=int(round(total_seconds * 1000)) if total_seconds else None,
            segments=tuple(collected),
        )

    def unload_model(self) -> None:
        if self._model is not None:
            logger.info("Unloading model '%s'.", self._model_name)
            self._model = None
