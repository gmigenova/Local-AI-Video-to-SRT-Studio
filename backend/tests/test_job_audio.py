"""Tests for GET /jobs/{job_id}/audio — the waveform source for the editor.

The endpoint serves the pipeline's extracted mono WAV; retention may have
removed the file for old jobs, which must surface as a clean 404.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from translation_fixtures import seed_translation_job

from app.core.config import get_settings
from app.main import app


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def _write_wav(path: Path, frames: int = 16) -> None:
    payload = b"\x00\x00" * frames
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(payload))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
        + b"data"
        + struct.pack("<I", len(payload))
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + payload)


def test_job_audio_served(client: TestClient) -> None:
    job_id = seed_translation_job(["Hello"])
    _write_wav(get_settings().storage_subdir("audio") / job_id / "extracted.wav")

    response = client.get(f"/api/v1/jobs/{job_id}/audio")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content[:4] == b"RIFF"


def test_job_audio_404_when_retention_removed_it(client: TestClient) -> None:
    job_id = seed_translation_job(["Hello"])  # no extracted.wav on disk

    response = client.get(f"/api/v1/jobs/{job_id}/audio")

    assert response.status_code == 404
    assert "No extracted audio" in response.json()["detail"]


def test_job_audio_404_unknown_job(client: TestClient) -> None:
    response = client.get("/api/v1/jobs/nope/audio")
    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found."
