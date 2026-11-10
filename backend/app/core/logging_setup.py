"""Logging configuration: console + rotating file handler."""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from app.core.config import get_settings

_CONFIGURED = False

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def configure_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    """Configure root logging once (subsequent calls only adjust the level)."""
    global _CONFIGURED
    log_dir = log_dir or get_settings().abs_logs_path
    root = logging.getLogger()

    if _CONFIGURED:
        root.setLevel(level.upper())
        return

    root.setLevel(level.upper())
    formatter = logging.Formatter(_FORMAT)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    root.addHandler(console)

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "app.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:  # pragma: no cover - logging must never crash the app
        root.warning("Could not open log file in %s; logging to console only.", log_dir)

    _CONFIGURED = True
