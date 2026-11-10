"""GET /health (section 10.1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.base import get_db
from app.services.transcription.model_manager import ModelManager
from app.workers.heartbeat import is_worker_online

router = APIRouter()


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(text("SELECT 1"))
        database = "connected"
    except Exception:  # noqa: BLE001 - health must always answer
        database = "error"

    worker = "online" if is_worker_online() else "offline"
    gpu = ModelManager.gpu_summary().get("gpu_name") or "CPU"

    return {
        "status": "ok" if database == "connected" else "degraded",
        "database": database,
        "worker": worker,
        "gpu": gpu,
    }
