"""Worker heartbeat file + single-instance lock (§9).

The heartbeat is a small JSON file under ``logs/`` that the worker refreshes
on every poll and progress tick; the API health endpoint reads it to report
``worker: online/offline``. The lock file prevents two workers from claiming
jobs (and the GPU) concurrently.
"""

from __future__ import annotations

import json
import os
import time

from app.core.config import REPO_ROOT

HEARTBEAT_PATH = REPO_ROOT / "logs" / "worker.json"
LOCK_PATH = REPO_ROOT / "logs" / "worker.lock"
#: seconds after which a heartbeat is considered offline (2x poll + slack)
STALE_AFTER_SECONDS = 15.0
#: a lock older than this is considered abandoned (crashed worker)
LOCK_STALE_SECONDS = 900.0


def write_heartbeat(busy_job_id: str | None, model: str | None = None) -> None:
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": os.getpid(),
        "timestamp": time.time(),
        "busy_job_id": busy_job_id,
        "model": model,
    }
    tmp = HEARTBEAT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(HEARTBEAT_PATH)


def read_heartbeat() -> dict | None:
    try:
        data = json.loads(HEARTBEAT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("timestamp", 0)
    return data


def heartbeat_age_seconds() -> float | None:
    data = read_heartbeat()
    if data is None:
        return None
    return max(0.0, time.time() - float(data["timestamp"]))


def is_worker_online(max_age: float = STALE_AFTER_SECONDS) -> bool:
    age = heartbeat_age_seconds()
    return age is not None and age <= max_age


def acquire_lock() -> None:
    """Take the single-worker lock; raise RuntimeError if another is active."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_PATH.exists():
        age = time.time() - LOCK_PATH.stat().st_mtime
        if age < LOCK_STALE_SECONDS:
            raise RuntimeError(
                "Another AI worker appears to be running "
                f"(lock age {age:.0f}s). Delete {LOCK_PATH} if that is wrong."
            )
        LOCK_PATH.unlink(missing_ok=True)
    LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")


def release_lock() -> None:
    try:
        if LOCK_PATH.read_text(encoding="utf-8").strip() == str(os.getpid()):
            LOCK_PATH.unlink(missing_ok=True)
    except OSError:
        pass
