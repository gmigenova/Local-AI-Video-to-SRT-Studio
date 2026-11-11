"""Burn-in render tests: argument building, repository, API and manager.

The API's background render manager is replaced with a manual one (no
auto-loop) so tests control exactly when a render is claimed. FFmpeg is
only required for the end-to-end test at the bottom.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from conftest import requires_ffmpeg
from fastapi.testclient import TestClient
from test_pipeline import FakeEngine, FakeManager  # noqa: F401 (reused fakes)

from app.core.config import get_settings
from app.core.errors import OperationCancelled
from app.database.base import get_session_factory
from app.main import app
from app.models.render import RenderStatus
from app.repositories.renders import RendersRepository
from app.services.render.burner import BurnResult, build_burn_args, sanitize_font_name
from app.services.render.manager import RenderManager, set_render_manager


# ----------------------------------------------------------------------
# Test doubles
# ----------------------------------------------------------------------
class FakeBurner:
    """Instantly 'renders' a small file and records the call."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def burn(self, video_path, srt_path, output_path, **kwargs):  # noqa: ANN001, ANN003
        self.calls.append(
            {
                "video_path": str(video_path),
                "srt_path": str(srt_path),
                "output_path": str(output_path),
                **kwargs,
            }
        )
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"fake-mp4-bytes")
        if kwargs.get("on_progress") is not None:
            kwargs["on_progress"](1.0)
        return BurnResult(output_path=output, file_size=output.stat().st_size)


class BlockingBurner:
    """Stays inside burn() until the cancel event fires (cancellation test)."""

    def burn(self, video_path, srt_path, output_path, **kwargs):  # noqa: ANN001, ANN003
        cancel_event: threading.Event | None = kwargs.get("cancel_event")
        if cancel_event is not None:
            cancel_event.wait(timeout=10)
        raise OperationCancelled("Render cancelled.")


class ManualManager(RenderManager):
    """Manager whose loop never auto-starts - tests call process_once()."""

    def start(self) -> None:  # noqa: D102 - keep the queue manual
        pass


@pytest.fixture(autouse=True)
def manual_render_manager():
    manager = ManualManager(burner=FakeBurner())
    set_render_manager(manager)
    yield manager
    set_render_manager(None)


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def project_id(client: TestClient) -> str:
    response = client.post("/api/v1/projects", json={"name": "Render Project"})
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
    return response.json()["media_id"]


@pytest.fixture()
def clean_renders(client: TestClient):
    """Empty the global render queue so claim/recover tests are isolated."""
    from app.models.render import VideoRender

    db = get_session_factory()()
    try:
        for render in db.query(VideoRender).all():
            db.delete(render)
        db.commit()
    finally:
        db.close()


def drain_job_queue() -> None:
    """Claim-and-forget queued transcription jobs (isolate claim order)."""
    from app.repositories.jobs import JobsRepository

    db = get_session_factory()()
    try:
        repo = JobsRepository(db)
        while repo.claim_next() is not None:
            pass
    finally:
        db.close()


@pytest.fixture()
def completed_job_id(client: TestClient, media_id: str) -> str:
    """A finished transcription job (fake engine) with one subtitle row."""
    from app.pipeline import TranscriptionPipeline
    from app.workers.worker import JobWorker

    drain_job_queue()
    job_id = client.post(
        "/api/v1/jobs", json={"media_id": media_id, "model": "tiny", "language": "en"}
    ).json()["job_id"]
    worker = JobWorker(
        settings=get_settings(),
        session_factory=get_session_factory(),
        pipeline_factory=lambda: TranscriptionPipeline(
            settings=get_settings(), model_manager=FakeManager(FakeEngine())  # type: ignore[arg-type]
        ),
    )
    assert worker.process_once() == job_id
    return job_id


# ----------------------------------------------------------------------
# Unit: argument building (no FFmpeg needed)
# ----------------------------------------------------------------------
class TestBuildBurnArgs:
    def test_basic_structure(self, tmp_path: Path):
        args = build_burn_args(
            tmp_path / "video.mp4", tmp_path / "render.srt", tmp_path / "out.mp4"
        )
        assert args[0] == "ffmpeg"
        assert "-nostdin" in args
        assert "-y" in args
        # filter references the bare SRT name (cwd trick, Windows-safe)
        assert args[args.index("-vf") + 1] == "subtitles=render.srt"
        # first video stream, optional first audio stream
        assert args[args.index("-map") + 1] == "0:v:0"
        assert "0:a:0?" in args
        # output is the last argument
        assert args[-1] == str(tmp_path / "out.mp4")

    def test_audio_copy_for_mp4_safe_codecs(self, tmp_path: Path):
        paths = (tmp_path / "v.mp4", tmp_path / "render.srt", tmp_path / "o.mp4")
        for codec in ("aac", "mp3", "ac3"):
            args = build_burn_args(*paths, audio_codec=codec)
            i = args.index("-c:a")
            assert args[i + 1] == "copy"

    def test_audio_transcoded_otherwise(self, tmp_path: Path):
        paths = (tmp_path / "v.webm", tmp_path / "render.srt", tmp_path / "o.mp4")
        for codec in ("opus", "vorbis", None):
            args = build_burn_args(*paths, audio_codec=codec)
            i = args.index("-c:a")
            assert args[i + 1] == "aac"

    def test_force_style_only_with_font(self, tmp_path: Path):
        paths = (tmp_path / "v.mp4", tmp_path / "render.srt", tmp_path / "o.mp4")
        plain = build_burn_args(*paths)
        assert "force_style" not in plain[plain.index("-vf") + 1]

        styled = build_burn_args(*paths, font_name="Leelawadee UI")
        filter_value = styled[styled.index("-vf") + 1]
        assert filter_value == "subtitles=render.srt:force_style='FontName=Leelawadee UI'"

    def test_rejects_unexpected_srt_name(self, tmp_path: Path):
        with pytest.raises(ValueError):
            build_burn_args(
                tmp_path / "v.mp4", tmp_path / "output.srt", tmp_path / "o.mp4"
            )

    def test_sanitize_font_name(self):
        assert sanitize_font_name("Arial:Bold'\\") == "ArialBold"


# ----------------------------------------------------------------------
# Repository
# ----------------------------------------------------------------------
class TestRendersRepository:
    def test_lifecycle(self, client, completed_job_id, clean_renders):
        db = get_session_factory()()
        try:
            repo = RendersRepository(db)
            render = repo.create(completed_job_id, font_name="Tahoma")
            assert render.status == "queued"
            assert repo.active_for_job(completed_job_id) is not None
            assert repo.latest_for_job(completed_job_id).id == render.id

            assert repo.claim_next() == render.id
            assert repo.get(render.id).status == "running"

            repo.set_progress(render.id, 42.0, "Burning subtitles")
            assert repo.get(render.id).progress == 42.0

            repo.update_status(render.id, RenderStatus.COMPLETED, complete=True)
            done = repo.get(render.id)
            assert done.status == "completed"
            assert done.completed_at is not None
            assert repo.active_for_job(completed_job_id) is None
        finally:
            db.close()

    def test_cancel_queued(self, client, completed_job_id):
        db = get_session_factory()()
        try:
            repo = RendersRepository(db)
            render = repo.create(completed_job_id)
            assert repo.request_cancel(render.id) == "cancelled"
        finally:
            db.close()

    def test_claim_is_exclusive(self, client, completed_job_id, clean_renders):
        db = get_session_factory()()
        try:
            repo = RendersRepository(db)
            first = repo.create(completed_job_id)
            second = repo.create(completed_job_id)
            assert repo.claim_next() == first.id
            assert repo.claim_next() == second.id
            assert repo.claim_next() is None
        finally:
            db.close()

    def test_recover_stale(self, client, completed_job_id, clean_renders):
        db = get_session_factory()()
        try:
            repo = RendersRepository(db)
            running = repo.create(completed_job_id)
            assert repo.claim_next() == running.id
            cancelling = repo.create(completed_job_id)
            repo.request_cancel(cancelling.id)

            recovered = repo.recover_stale()
            assert recovered == 1  # only the running one
            assert repo.get(running.id).status == "queued"
            assert repo.get(cancelling.id).status == "cancelled"
        finally:
            db.close()


# ----------------------------------------------------------------------
# API + manager
# ----------------------------------------------------------------------
class TestRenderApi:
    def test_render_requires_completed_job(self, client, media_id):
        job_id = client.post(
            "/api/v1/jobs", json={"media_id": media_id, "model": "tiny"}
        ).json()["job_id"]
        response = client.post(f"/api/v1/jobs/{job_id}/render")
        assert response.status_code == 409
        assert "completed" in response.json()["detail"]

    def test_render_unknown_job_404(self, client):
        assert client.post("/api/v1/jobs/nope/render").status_code == 404

    @requires_ffmpeg
    def test_render_requires_subtitles(self, client, completed_job_id):
        from app.repositories.subtitles import SubtitlesRepository

        db = get_session_factory()()
        try:
            SubtitlesRepository(db).replace_for_job(completed_job_id, [])
            db.commit()
        finally:
            db.close()
        response = client.post(f"/api/v1/jobs/{completed_job_id}/render")
        assert response.status_code == 409
        assert "no subtitles" in response.json()["detail"]

    @requires_ffmpeg
    def test_full_render_lifecycle_with_fake_burner(
        self, client, completed_job_id, manual_render_manager, clean_renders
    ):
        # no render yet
        assert client.get(f"/api/v1/jobs/{completed_job_id}/render").status_code == 404

        created = client.post(
            f"/api/v1/jobs/{completed_job_id}/render",
            json={"font_name": "Tahoma"},
        )
        assert created.status_code == 201, created.text
        body = created.json()
        render_id = body["render_id"]
        assert body["status"] == "queued"

        # only one active render per job
        assert client.post(f"/api/v1/jobs/{completed_job_id}/render").status_code == 409

        latest = client.get(f"/api/v1/jobs/{completed_job_id}/render").json()
        assert latest["render_id"] == render_id

        # download not ready before the render runs
        assert client.get(f"/api/v1/renders/{render_id}/download").status_code == 409

        assert manual_render_manager.process_once() == render_id
        done = client.get(f"/api/v1/renders/{render_id}").json()
        assert done["status"] == "completed"
        assert done["progress"] == 100.0
        assert done["font_name"] == "Tahoma"

        # the burner received the current subtitles as render.srt
        call = manual_render_manager._burner.calls[0]
        assert Path(call["srt_path"]).read_text(encoding="utf-8").startswith("1")

        # download works once completed
        download = client.get(f"/api/v1/renders/{render_id}/download")
        assert download.status_code == 200
        assert download.headers["content-type"].startswith("video/mp4")
        assert download.content == b"fake-mp4-bytes"

        # a new render can be started after completion
        again = client.post(f"/api/v1/jobs/{completed_job_id}/render")
        assert again.status_code == 201

    @requires_ffmpeg
    def test_cancel_running_render(
        self, client, completed_job_id, manual_render_manager, clean_renders
    ):
        manual_render_manager._burner = BlockingBurner()
        render_id = client.post(
            f"/api/v1/jobs/{completed_job_id}/render"
        ).json()["render_id"]

        result: list[str | None] = []
        thread = threading.Thread(
            target=lambda: result.append(manual_render_manager.process_once())
        )
        thread.start()

        # wait until the burner is inside burn()
        for _ in range(50):
            if manual_render_manager._cancel_events:
                break
            threading.Event().wait(0.1)
        assert manual_render_manager._cancel_events, "burn() never started"

        cancelled = client.post(f"/api/v1/renders/{render_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelling"

        thread.join(timeout=10)
        assert result == [render_id]
        final = client.get(f"/api/v1/renders/{render_id}").json()
        assert final["status"] == "cancelled"
        assert client.get(f"/api/v1/renders/{render_id}/download").status_code == 409

    def test_cancel_requires_active(self, client, completed_job_id, clean_renders):
        render_id = client.post(
            f"/api/v1/jobs/{completed_job_id}/render"
        ).json()["render_id"]
        # queued renders cancel immediately
        first = client.post(f"/api/v1/renders/{render_id}/cancel")
        assert first.status_code == 200
        assert first.json()["status"] == "cancelled"

        # a cancelled render can no longer be cancelled
        assert client.post(f"/api/v1/renders/{render_id}/cancel").status_code == 409


# ----------------------------------------------------------------------
# End-to-end with real FFmpeg
# ----------------------------------------------------------------------
class TestRealBurn:
    @requires_ffmpeg
    def test_burn_real_video(self, client, completed_job_id, clean_renders):
        from app.services.render.burner import SubtitleBurner

        manager = ManualManager(burner=SubtitleBurner())
        set_render_manager(manager)
        try:
            render_id = client.post(
                f"/api/v1/jobs/{completed_job_id}/render"
            ).json()["render_id"]
            assert manager.process_once() == render_id

            done = client.get(f"/api/v1/renders/{render_id}").json()
            assert done["status"] == "completed", done
            assert done["file_size"] > 0

            output = (
                get_settings().storage_subdir("renders") / render_id / "output.mp4"
            )
            assert output.is_file()

            download = client.get(f"/api/v1/renders/{render_id}/download")
            assert download.status_code == 200
            assert download.headers["content-type"].startswith("video/mp4")
            assert "subtitled" in download.headers.get("content-disposition", "")
        finally:
            set_render_manager(None)
