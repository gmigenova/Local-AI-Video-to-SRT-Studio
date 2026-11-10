"""Model lifecycle manager (section 3.3 of the specification).

Ensures that at most one model instance is loaded at a time, so a single
12 GB GPU is not exhausted by duplicate models, and that switching models
unloads the previous one.  A model is *not* reloaded per job: the loaded
engine is cached and reused while the model identity stays the same.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading

from app.core.config import Settings, get_settings
from app.services.transcription.engine import TranscriptionEngine
from app.services.transcription.faster_whisper_engine import FasterWhisperEngine

logger = logging.getLogger(__name__)

_ENGINE_KEY = tuple[str, str, str]  # (model_name, device, compute_type)


class ModelManager:
    """Loads, caches and swaps transcription engines."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._engine: TranscriptionEngine | None = None
        self._engine_key: _ENGINE_KEY | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Engine access
    # ------------------------------------------------------------------
    def get_engine(
        self,
        model_name: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
    ) -> TranscriptionEngine:
        """Return a loaded engine for the requested model, loading if needed.

        If a different model/device/compute-type is currently loaded, it is
        unloaded first to free VRAM/RAM.
        """
        key: _ENGINE_KEY = (
            model_name or self._settings.whisper_model,
            device or self._settings.whisper_device,
            compute_type or self._settings.whisper_compute_type,
        )
        with self._lock:
            if self._engine is not None and self._engine_key == key:
                return self._engine
            if self._engine is not None:
                logger.info(
                    "Switching model %s -> %s; unloading previous model.",
                    self._engine_key,
                    key,
                )
                self._engine.unload_model()
                self._engine = None
                self._engine_key = None

            engine: FasterWhisperEngine = FasterWhisperEngine(
                model_name=key[0],
                device=key[1],
                compute_type=key[2],
                download_root=self._settings.whisper_download_root,
            )
            engine.load_model()
            self._engine = engine
            self._engine_key = key
            return engine

    def current_model(self) -> str | None:
        with self._lock:
            return self._engine.model_name if self._engine else None

    def is_loaded(self) -> bool:
        with self._lock:
            return self._engine is not None and self._engine.is_loaded()

    def unload(self) -> None:
        with self._lock:
            if self._engine is not None:
                self._engine.unload_model()
                self._engine = None
                self._engine_key = None

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    @staticmethod
    def gpu_summary() -> dict:
        """Best-effort GPU/runtime diagnostics for /system/info."""
        summary: dict = {
            "ctranslate2_cuda_devices": 0,
            "ctranslate2_devices": 0,
            "gpu_name": None,
            "gpu_vram_total_mb": None,
            "nvidia_driver": None,
            "cuda_runtime_available": False,
            "note": None,
        }
        try:
            import ctranslate2

            summary["ctranslate2_cuda_devices"] = ctranslate2.get_cuda_device_count()
            summary["ctranslate2_devices"] = ctranslate2.get_device_count()
            summary["cuda_runtime_available"] = summary["ctranslate2_cuda_devices"] > 0
        except Exception as exc:  # pragma: no cover
            summary["note"] = f"ctranslate2 introspection failed: {exc}"

        nvidia_smi = shutil.which("nvidia-smi")
        if nvidia_smi:
            try:
                completed = subprocess.run(  # noqa: S603 - fixed argv
                    [
                        nvidia_smi,
                        "--query-gpu=name,memory.total,driver_version",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if completed.returncode == 0 and completed.stdout.strip():
                    name, vram, driver = (
                        part.strip() for part in completed.stdout.strip().split(",", 2)
                    )
                    summary["gpu_name"] = name
                    summary["gpu_vram_total_mb"] = int(vram)
                    summary["nvidia_driver"] = driver
            except (OSError, ValueError):
                pass

        if not summary["cuda_runtime_available"]:
            summary["note"] = (
                "No CUDA devices visible to CTranslate2. Native Windows builds are "
                "CPU-only; run under WSL2/Docker for GPU inference."
            )
        return summary
