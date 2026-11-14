"""GET /system/info (section 10.2)."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess

from fastapi import APIRouter

from app.core.config import MODEL_CATALOG, get_settings
from app.services.diarization import DiarizationService
from app.services.transcription.model_manager import ModelManager
from app.workers.heartbeat import is_worker_online, read_heartbeat

router = APIRouter()


def _total_ram_gb() -> float | None:
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
        return round(stat.ullTotalPhys / 1024**3, 1)
    except Exception:  # noqa: BLE001 - non-Windows or restricted
        return None


def _ffmpeg_version(ffmpeg_path: str) -> str | None:
    if shutil.which(ffmpeg_path) is None:
        return None
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv
            [ffmpeg_path, "-version"], capture_output=True, text=True, timeout=10
        )
        first = (completed.stdout or "").strip().splitlines()
        return first[0] if first else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _installed_models() -> list[str]:
    """Model names found under models/faster-whisper (any cache layout)."""
    root = get_settings().whisper_download_root
    known = set(MODEL_CATALOG)
    found: set[str] = set()
    if root.is_dir():
        for model_bin in root.glob("**/model.bin"):
            for part in model_bin.parts:
                if part in known:
                    found.add(part)
                elif part.startswith("models--Systran--faster-whisper-"):
                    name = part.split("faster-whisper-", 1)[1]
                    if name in known:
                        found.add(name)
    return sorted(found)


@router.get("/system/info")
def system_info() -> dict:
    settings = get_settings()
    gpu = ModelManager.gpu_summary()
    beat = read_heartbeat() or {}
    diarization_available, diarization_reason = DiarizationService.is_available(settings)
    return {
        "app_name": settings.app_name,
        "app_env": settings.app_env,
        "cpu": platform.processor() or platform.machine(),
        "cpu_cores": os.cpu_count(),
        "total_ram_gb": _total_ram_gb(),
        "gpu": {
            "name": gpu.get("gpu_name"),
            "vram_total_mb": gpu.get("gpu_vram_total_mb"),
            "cuda_available": gpu.get("cuda_runtime_available", False),
            "ctranslate2_cuda_devices": gpu.get("ctranslate2_cuda_devices", 0),
            "note": gpu.get("note"),
        },
        "ffmpeg_version": _ffmpeg_version(settings.ffmpeg_path),
        "models_available": [
            {"name": name, "profile": meta["profile"], "installed": name in _installed_models()}
            for name, meta in MODEL_CATALOG.items()
        ],
        "worker": {
            "online": is_worker_online(),
            "pid": beat.get("pid"),
            "busy_job_id": beat.get("busy_job_id"),
        },
        "diarization": {
            "available": diarization_available,
            "reason": diarization_reason,
            "model": settings.diarize_model,
        },
    }
