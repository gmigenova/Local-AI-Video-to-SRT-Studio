"""Tests for GET /jobs/{job_id}/transcript — the confidence-highlighting
source for the editor.

The endpoint serves the pipeline's raw transcript.json (segments with
per-word probability). Imported-SRT jobs never had one, and retention may
have removed it for old jobs — both must surface as a clean 404.
"""

from __future__ import annotations

import json
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


def _write_transcript(path: Path) -> None:
    payload = {
        "language": "en",
        "language_probability": 0.98,
        "duration_ms": 4000,
        "segments": [
            {
                "start_ms": 0,
                "end_ms": 2000,
                "text": "Hello",
                "confidence": 0.55,
                "words": [
                    {"start_ms": 0, "end_ms": 500, "word": "Hello", "probability": 0.55}
                ],
            }
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_job_transcript_served(client: TestClient) -> None:
    job_id = seed_translation_job(["Hello"])
    _write_transcript(
        get_settings().storage_subdir("transcripts") / job_id / "transcript.json"
    )

    response = client.get(f"/api/v1/jobs/{job_id}/transcript")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["segments"][0]["words"][0]["probability"] == 0.55


def test_job_transcript_404_when_missing(client: TestClient) -> None:
    job_id = seed_translation_job(["Hello"])  # no transcript.json on disk

    response = client.get(f"/api/v1/jobs/{job_id}/transcript")

    assert response.status_code == 404
    assert "No raw transcript" in response.json()["detail"]


def test_job_transcript_404_unknown_job(client: TestClient) -> None:
    response = client.get("/api/v1/jobs/nope/transcript")
    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found."
