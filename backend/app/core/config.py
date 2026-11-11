"""Application settings.

Values come from environment variables and the repository-root ``.env`` file
(see ``.env.example``).  No absolute user-specific paths are hardcoded: every
path is resolved relative to the repository root, which is derived from this
file's location.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# backend/app/core/config.py -> repository root is three levels up.
REPO_ROOT = Path(__file__).resolve().parents[3]

#: Video containers accepted for upload (validated again via FFprobe).
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v"}

#: Curated models offered in the UI. Development models are usable from the
#: CLI for smoke tests but are not intended for production quality.
MODEL_CATALOG: dict[str, dict[str, str]] = {
    "large-v3": {"profile": "quality", "note": "Best accuracy (default)"},
    "large-v3-turbo": {"profile": "balanced", "note": "Faster, near-large accuracy"},
    "medium": {"profile": "dev", "note": "Development / smoke tests"},
    "small": {"profile": "dev", "note": "Development / smoke tests"},
    "tiny": {"profile": "dev", "note": "Development / smoke tests"},
}
DEFAULT_MODEL = "large-v3"


class Settings(BaseSettings):
    """Typed application settings loaded from the environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "VideoToSRT"
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    # Database
    database_url: str = "sqlite:///./data/database/app.db"

    # Storage
    storage_path: Path = Path("./storage")
    model_path: Path = Path("./models")
    logs_path: Path = Path("./logs")

    # Whisper / inference
    whisper_model: str = DEFAULT_MODEL
    whisper_device: str = "auto"  # auto | cuda | cpu
    whisper_compute_type: str = "auto"  # auto | float16 | int8 | int8_float16 ...
    enable_vad: bool = True
    enable_word_timestamps: bool = True

    # Worker
    worker_poll_interval: float = 2.0
    max_gpu_workers: int = 1

    # Uploads
    max_upload_size_gb: float = 20.0

    # Google Cloud Translation API (subtitle translation; empty key = disabled)
    google_translate_api_key: str = ""
    google_translate_timeout_seconds: float = 30.0
    #: monthly character budget (Google meters per character); 0 = unlimited
    google_translate_monthly_char_limit: int = 500_000

    # Retention / automatic cleanup (days; 0 disables the rule)
    retention_temp_days: int = 7
    retention_audio_days: int = 14
    retention_artifact_days: int = 0  # transcripts + subtitle exports: keep forever

    # External tools
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    ffmpeg_timeout_seconds: int = 3600

    # Logging
    log_level: str = "INFO"

    # ------------------------------------------------------------------
    # Path resolution helpers
    # ------------------------------------------------------------------
    def _resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else (REPO_ROOT / path).resolve()

    @property
    def abs_storage_path(self) -> Path:
        return self._resolve(self.storage_path)

    @property
    def abs_model_path(self) -> Path:
        return self._resolve(self.model_path)

    @property
    def abs_logs_path(self) -> Path:
        return self._resolve(self.logs_path)

    @property
    def abs_database_path(self) -> Path:
        """Filesystem path of the SQLite database (for mkdir purposes)."""
        url = self.database_url
        prefix = "sqlite:///"
        if url.startswith(prefix):
            raw = Path(url[len(prefix) :])
            return self._resolve(raw)
        raise NotImplementedError(f"Non-SQLite database URL is not supported yet: {url}")

    @property
    def whisper_download_root(self) -> Path:
        return self.abs_model_path / "faster-whisper"

    def storage_subdir(self, name: str) -> Path:
        return self.abs_storage_path / name

    def ensure_directories(self) -> None:
        """Create all runtime directories (idempotent)."""
        for sub in ("uploads", "audio", "transcripts", "subtitles", "temp"):
            (self.abs_storage_path / sub).mkdir(parents=True, exist_ok=True)
        self.whisper_download_root.mkdir(parents=True, exist_ok=True)
        self.abs_database_path.parent.mkdir(parents=True, exist_ok=True)
        self.abs_logs_path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached singleton settings instance."""
    return Settings()
