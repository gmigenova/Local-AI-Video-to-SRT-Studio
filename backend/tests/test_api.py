"""Phase 2 API + worker integration tests.

Environment is redirected to a temp database/storage directory in
``conftest.py`` *before* any app import, so these tests never touch the
developer's real data.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from conftest import requires_ffmpeg
from fastapi.testclient import TestClient
from test_pipeline import FakeEngine, FakeManager  # noqa: F401 (reused fakes)

from app.core.config import get_settings
from app.database.base import get_session_factory
from app.main import app
from app.models.job import JobStatus
from app.repositories.jobs import JobsRepository
from app.repositories.subtitles import SubtitlesRepository
from app.workers.worker import JobWorker


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def project_id(client: TestClient) -> str:
    response = client.post(
        "/api/v1/projects", json={"name": "Test Project", "description": "integration"}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture()
def media_id(client: TestClient, project_id: str, sample_video: Path) -> str:
    with open(sample_video, "rb") as handle:
        response = client.post(
            "/api/v1/media/upload",
            files={"file": ("sample.mp4", handle, "video/mp4")},
            data={"project_id": project_id, "audio_stream_index": "0"},
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["filename"] == "sample.mp4"
    assert body["duration_ms"] is not None and body["duration_ms"] > 1000
    assert len(body["audio_streams"]) == 1
    return body["media_id"]


@pytest.fixture()
def worker() -> JobWorker:
    """Real worker loop with a fake transcription engine injected."""
    return JobWorker(
        settings=get_settings(),
        session_factory=get_session_factory(),
        pipeline_factory=lambda: _fake_pipeline(),
    )


def _fake_pipeline():
    from app.pipeline import TranscriptionPipeline

    return TranscriptionPipeline(
        settings=get_settings(),
        model_manager=FakeManager(FakeEngine()),  # type: ignore[arg-type]
    )


def drain_queue() -> None:
    """Claim-and-forget every queued job so claim-order tests are isolated."""
    db = get_session_factory()()
    try:
        repo = JobsRepository(db)
        while repo.claim_next() is not None:
            pass
    finally:
        db.close()


class TestHealthAndProjects:
    def test_health(self, client: TestClient):
        body = client.get("/api/v1/health").json()
        assert body["status"] == "ok"
        assert body["database"] == "connected"
        assert body["worker"] in ("online", "offline")

    def test_system_info(self, client: TestClient):
        body = client.get("/api/v1/system/info").json()
        assert "gpu" in body and "models_available" in body
        assert any(m["name"] == "large-v3" for m in body["models_available"])

    def test_project_crud(self, client: TestClient):
        created = client.post("/api/v1/projects", json={"name": "P2"})
        assert created.status_code == 201
        pid = created.json()["id"]
        assert client.get(f"/api/v1/projects/{pid}").json()["name"] == "P2"
        listing = client.get("/api/v1/projects")
        assert any(p["id"] == pid for p in listing.json())
        assert client.delete(f"/api/v1/projects/{pid}").status_code == 204
        assert client.get(f"/api/v1/projects/{pid}").status_code == 404

    def test_project_rename_and_edit(self, client: TestClient):
        pid = client.post(
            "/api/v1/projects", json={"name": "Old", "description": "keep me"}
        ).json()["id"]

        renamed = client.patch(f"/api/v1/projects/{pid}", json={"name": "  New Name  "})
        assert renamed.status_code == 200
        body = renamed.json()
        assert body["name"] == "New Name"  # trimmed
        assert body["description"] == "keep me"  # untouched by a name-only patch

        cleared = client.patch(f"/api/v1/projects/{pid}", json={"description": ""})
        assert cleared.status_code == 200
        assert cleared.json()["description"] is None
        assert cleared.json()["name"] == "New Name"

        assert (
            client.patch(f"/api/v1/projects/{pid}", json={"name": "   "}).status_code == 400
        )
        assert (
            client.patch("/api/v1/projects/not-a-uuid", json={"name": "x"}).status_code == 404
        )
        client.delete(f"/api/v1/projects/{pid}")


class TestProjectDelete:
    """DELETE /projects/{id}: guards + on-disk cleanup."""

    def _force_status(self, job_id: str, status: JobStatus) -> None:
        db = get_session_factory()()
        try:
            JobsRepository(db).update_status(job_id, status)
        finally:
            db.close()

    def test_delete_blocked_while_job_active(
        self, client: TestClient, project_id: str, media_id: str
    ):
        created = client.post(
            "/api/v1/jobs", json={"media_id": media_id, "model": "tiny", "language": None}
        )
        assert created.status_code == 201
        job_id = created.json()["job_id"]

        blocked = client.delete(f"/api/v1/projects/{project_id}")
        assert blocked.status_code == 409
        assert "cancel" in blocked.json()["detail"].lower()

        # terminal jobs no longer block the delete
        self._force_status(job_id, JobStatus.FAILED)
        assert client.delete(f"/api/v1/projects/{project_id}").status_code == 204
        assert client.get(f"/api/v1/projects/{project_id}").status_code == 404

    def test_delete_blocked_while_render_running(
        self,
        client: TestClient,
        project_id: str,
        media_id: str,
        worker: JobWorker,
    ):
        created = client.post(
            "/api/v1/jobs", json={"media_id": media_id, "model": "tiny", "language": None}
        )
        job_id = created.json()["job_id"]
        assert worker.process_once() == job_id  # completed, subtitles written

        from app.models.render import RenderStatus
        from app.repositories.renders import RendersRepository

        db = get_session_factory()()
        try:
            render = RendersRepository(db).create(job_id=job_id)
            # 'running' rows are never claimed by the manager loop, so this
            # state is stable for the duration of the test
            RendersRepository(db).update_status(render.id, RenderStatus.RUNNING, stage="Burning")

            blocked = client.delete(f"/api/v1/projects/{project_id}")
            assert blocked.status_code == 409
            assert "render" in blocked.json()["detail"].lower()

            RendersRepository(db).update_status(
                render.id, RenderStatus.COMPLETED, complete=True
            )
        finally:
            db.close()

        # with the render finished the project (and its render dir) go away
        render_dir = get_settings().storage_subdir("renders") / render.id
        render_dir.mkdir(parents=True, exist_ok=True)
        (render_dir / "hardsub.mp4").write_bytes(b"f")
        assert client.delete(f"/api/v1/projects/{project_id}").status_code == 204
        assert not render_dir.exists()
        assert client.get(f"/api/v1/projects/{project_id}").status_code == 404


class TestUploadValidation:
    def test_reject_unsupported_extension(self, client: TestClient, project_id: str):
        response = client.post(
            "/api/v1/media/upload",
            files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
            data={"project_id": project_id},
        )
        assert response.status_code == 400
        assert "Unsupported" in response.json()["detail"]

    def test_reject_unknown_project(self, client: TestClient, sample_video: Path):
        with open(sample_video, "rb") as handle:
            response = client.post(
                "/api/v1/media/upload",
                files={"file": ("v.mp4", handle, "video/mp4")},
                data={"project_id": "not-a-uuid"},
            )
        assert response.status_code == 404

    @requires_ffmpeg
    def test_media_listing_and_stream(self, client: TestClient, project_id, media_id):
        media = client.get(f"/api/v1/media/{media_id}").json()
        assert media["original_name"] == "sample.mp4"
        assert "file_path" not in media  # internal path never exposed (§16)

        streams = client.get(f"/api/v1/media/{media_id}/streams").json()
        assert len(streams) >= 1

        # audio stream selection (§11.2): valid absolute index -> 200
        patched = client.patch(
            f"/api/v1/media/{media_id}", json={"stream_index": streams[0]["stream_index"]}
        )
        assert patched.status_code == 200
        assert patched.json()["audio_stream_index"] == 0

        # invalid stream index -> 400
        bad = client.patch(f"/api/v1/media/{media_id}", json={"stream_index": 99})
        assert bad.status_code == 400

        full = client.get(f"/api/v1/media/{media_id}/stream")
        assert full.status_code == 200

        partial = client.get(
            f"/api/v1/media/{media_id}/stream", headers={"Range": "bytes=0-1023"}
        )
        assert partial.status_code == 206
        assert partial.headers["content-range"].startswith("bytes 0-1023/")
        assert len(partial.content) == 1024


class TestJobLifecycle:
    def test_create_job_validates_model(self, client, media_id):
        response = client.post(
            "/api/v1/jobs", json={"media_id": media_id, "model": "gpt-4"}
        )
        assert response.status_code == 400

    def test_create_job_unknown_media(self, client):
        assert client.post(
            "/api/v1/jobs", json={"media_id": "missing", "model": "tiny"}
        ).status_code == 404

    def test_create_job_rejects_unknown_settings(self, client, media_id):
        response = client.post(
            "/api/v1/jobs",
            json={"media_id": media_id, "model": "tiny", "settings": {"no_such": 1}},
        )
        assert response.status_code == 400

    @requires_ffmpeg
    def test_full_worker_lifecycle(self, client, media_id, worker):
        drain_queue()
        created = client.post(
            "/api/v1/jobs",
            json={"media_id": media_id, "model": "tiny", "language": "en"},
        )
        assert created.status_code == 201
        job_id = created.json()["job_id"]
        assert created.json()["status"] == "queued"

        assert worker.process_once() == job_id

        job = client.get(f"/api/v1/jobs/{job_id}").json()
        assert job["status"] == "completed"
        assert job["progress"] == 100.0
        assert job["detected_language"] == "en"

        subtitles = client.get(f"/api/v1/jobs/{job_id}/subtitles").json()
        assert len(subtitles) == 1
        assert subtitles[0]["text"] == "Hello world."
        assert subtitles[0]["is_edited"] is False

        # raw transcript persisted per §8
        transcript = (
            get_settings().storage_subdir("transcripts") / job_id / "transcript.json"
        )
        assert transcript.is_file()

        # initial SRT generated by the worker
        srt = get_settings().storage_subdir("subtitles") / job_id / "output.srt"
        assert srt.is_file()

        # raw segments persisted
        db = get_session_factory()()
        try:
            rows = SubtitlesRepository(db).list_for_job(job_id)
            assert rows[0].subtitle_index == 1
        finally:
            db.close()

    @requires_ffmpeg
    def test_worker_returns_none_when_idle(self, worker):
        drain_queue()
        assert worker.process_once() is None


class TestCancelAndRetry:
    def test_cancel_queued_job(self, client, media_id):
        job_id = client.post(
            "/api/v1/jobs", json={"media_id": media_id, "model": "tiny"}
        ).json()["job_id"]
        response = client.post(f"/api/v1/jobs/{job_id}/cancel")
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"

    def test_retry_requires_failed_or_cancelled(self, client, media_id):
        job_id = client.post(
            "/api/v1/jobs", json={"media_id": media_id, "model": "tiny"}
        ).json()["job_id"]
        assert client.post(f"/api/v1/jobs/{job_id}/retry").status_code == 409
        client.post(f"/api/v1/jobs/{job_id}/cancel")
        retried = client.post(f"/api/v1/jobs/{job_id}/retry")
        assert retried.status_code == 200
        assert retried.json()["status"] == "queued"

    def test_worker_recovery_requeues_stale_jobs(self, client, media_id):
        job_id = client.post(
            "/api/v1/jobs", json={"media_id": media_id, "model": "tiny"}
        ).json()["job_id"]
        db = get_session_factory()()
        try:
            JobsRepository(db).update_status(job_id, JobStatus.TRANSCRIBING)
            recovered = JobsRepository(db).recover_stale_jobs()
            assert recovered >= 1
            job = JobsRepository(db).get(job_id)
            assert job is not None and job.status == "queued"
        finally:
            db.close()


class TestSubtitleEditing:
    @requires_ffmpeg
    def test_update_bulk_reprocess_and_export(self, client, media_id, worker):
        drain_queue()
        job_id = client.post(
            "/api/v1/jobs", json={"media_id": media_id, "model": "tiny"}
        ).json()["job_id"]
        assert worker.process_once() == job_id

        subtitles = client.get(f"/api/v1/jobs/{job_id}/subtitles").json()
        sub_id = subtitles[0]["id"]

        # invalid timestamps rejected
        bad = client.put(
            f"/api/v1/jobs/{job_id}/subtitles/{sub_id}",
            json={"start_ms": 5000, "end_ms": 1000},
        )
        assert bad.status_code == 400

        # single edit
        edited = client.put(
            f"/api/v1/jobs/{job_id}/subtitles/{sub_id}",
            json={"text": "Edited text.", "end_ms": 4000},
        )
        assert edited.status_code == 200
        assert edited.json()["is_edited"] is True
        assert edited.json()["text"] == "Edited text."

        # bulk update
        bulk = client.post(
            f"/api/v1/jobs/{job_id}/subtitles/bulk-update",
            json={"updates": [{"id": sub_id, "text": "Bulk text."}]},
        )
        assert bulk.status_code == 200
        assert bulk.json()["updated"] == 1

        # reprocess restores AI text without re-running AI
        repo = client.post(f"/api/v1/jobs/{job_id}/subtitles/reprocess")
        assert repo.status_code == 200
        assert repo.json()["subtitles"] == 1
        after = client.get(f"/api/v1/jobs/{job_id}/subtitles").json()
        assert after[0]["text"] == "Hello world."
        assert after[0]["is_edited"] is False

        # exports
        for fmt, expect in (
            ("srt", b"Hello world."),
            ("vtt", b"WEBVTT"),
            ("txt", b"Hello world."),
            ("json", b"Hello world."),
        ):
            export = client.get(f"/api/v1/jobs/{job_id}/export/{fmt}")
            assert export.status_code == 200, fmt
            assert expect in export.content
        assert "attachment" in client.get(
            f"/api/v1/jobs/{job_id}/export/srt"
        ).headers["content-disposition"]

    def test_export_unknown_format(self, client, media_id):
        job_id = client.post(
            "/api/v1/jobs", json={"media_id": media_id, "model": "tiny"}
        ).json()["job_id"]
        assert client.get(f"/api/v1/jobs/{job_id}/export/docx").status_code == 400

    @requires_ffmpeg
    def test_sync_full_state(self, client, media_id, worker):
        """Editor full-state save: edit + add + delete + renumber in one call."""
        drain_queue()
        job_id = client.post(
            "/api/v1/jobs", json={"media_id": media_id, "model": "tiny"}
        ).json()["job_id"]
        assert worker.process_once() == job_id

        # edit the existing row, add two rows (simulating split), drop none
        payload = {
            "subtitles": [
                {"start_ms": 1000, "end_ms": 2000, "text": "Edited.", "is_edited": True},
                {"start_ms": 2000, "end_ms": 3000, "text": "New row."},
                {"start_ms": 3000, "end_ms": 4000, "text": "Another.", "is_edited": False},
            ]
        }
        synced = client.post(f"/api/v1/jobs/{job_id}/subtitles/sync", json=payload)
        assert synced.status_code == 200, synced.text
        assert synced.json()["saved"] == 3

        rows = client.get(f"/api/v1/jobs/{job_id}/subtitles").json()
        assert [r["subtitle_index"] for r in rows] == [1, 2, 3]
        assert rows[0]["text"] == "Edited."
        assert rows[0]["is_edited"] is True
        assert rows[2]["text"] == "Another."

        # invalid timestamps rejected atomically (nothing saved)
        before = len(client.get(f"/api/v1/jobs/{job_id}/subtitles").json())
        bad = client.post(
            f"/api/v1/jobs/{job_id}/subtitles/sync",
            json={"subtitles": [{"start_ms": 5, "end_ms": 1, "text": "bad"}]},
        )
        assert bad.status_code == 400
        after = client.get(f"/api/v1/jobs/{job_id}/subtitles").json()
        assert len(after) == before
        assert after[0]["text"] == "Edited."

        # SRT file regenerated with the edited content
        srt = (get_settings().storage_subdir("subtitles") / job_id / "output.srt").read_text(
            encoding="utf-8"
        )
        assert "Edited." in srt
        assert "00:00:01,000 --> 00:00:02,000" in srt

    def test_export_no_subtitles_yet(self, client, media_id):
        job_id = client.post(
            "/api/v1/jobs", json={"media_id": media_id, "model": "tiny"}
        ).json()["job_id"]
        assert client.get(f"/api/v1/jobs/{job_id}/export/srt").status_code == 409


class TestJobClaiming:
    def test_claim_is_exclusive(self, client, media_id):
        # drain any queued jobs left by earlier tests, then test in isolation
        drain_queue()
        ids = [
            client.post(
                "/api/v1/jobs", json={"media_id": media_id, "model": "tiny"}
            ).json()["job_id"]
            for _ in range(2)
        ]
        db = get_session_factory()()
        try:
            repo = JobsRepository(db)
            first = repo.claim_next()
            second = repo.claim_next()
            assert first is not None and second is not None
            assert first != second
            assert {first, second} == set(ids)
            assert repo.claim_next() is None  # queue drained
        finally:
            db.close()
