"""Programmatic Alembic runner (used by API startup, worker and tests)."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]


def run_migrations() -> None:
    """Apply all pending Alembic migrations to the configured database."""
    from alembic import command
    from alembic.config import Config

    ini_path = BACKEND_DIR / "alembic.ini"
    if not ini_path.is_file():
        raise FileNotFoundError(f"alembic.ini not found at {ini_path}")
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(cfg, "head")
    logger.info("Database migrations applied.")
