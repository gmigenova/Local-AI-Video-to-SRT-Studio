"""FastAPI application factory (section 10).

Run from ``backend/``:
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.logging_setup import configure_logging
from app.database.base import init_database
from app.database.migrations import run_migrations
from app.services.export import ExportJobError
from app.services.media.upload_service import UploadRejected
from app.services.render import get_render_manager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.ensure_directories()
    init_database()
    try:
        run_migrations()
    except Exception as exc:  # noqa: BLE001 - API still boots read-only-ish
        logger.error("Migration failed at startup: %s", exc)
    # burn-in render loop (also requeues renders interrupted by a restart)
    render_manager = get_render_manager()
    render_manager.start()
    try:
        yield
    finally:
        render_manager.stop()


def _status_error_handler(status_code_attr: str = "status_code", message_attr: str = "message"):
    """Build a handler for service exceptions carrying (status_code, message)."""

    async def handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=int(getattr(exc, status_code_attr)),
            content={"detail": getattr(exc, message_attr, "Request failed.")},
        )

    return handler


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Local AI Video-to-SRT Studio API (fully local inference)",
        lifespan=lifespan,
    )
    app.add_exception_handler(UploadRejected, _status_error_handler())
    app.add_exception_handler(ExportJobError, _status_error_handler())

    # Dev frontend origins only; the app binds to localhost by default (§17).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
