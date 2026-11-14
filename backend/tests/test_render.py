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
from app.services.render.srt_import import (
    SrtImportError,
    decode_srt_bytes,
    normalise_srt,
    parse_srt,
)


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
class TestSrtImport:
    VALID = "1\n00:00:01,000 --> 00:00:03,500\nHello world\n\n2\n00:00:04,000 --> 00:00:06,000\nSecond cue\nwith two lines\n"

    def test_parse_valid(self):
        cues = parse_srt(self.VALID)
        assert len(cues) == 2
        assert cues[0].start_ms == 1000 and cues[0].end_ms == 3500
        assert cues[1].text == "Second cue\nwith two lines"

    def test_parse_tolerates_crlf_bom_and_dot_millis(self):
        raw = (
            "﻿1\r\n00:00:01.000 --> 00:00:02.000\r\nHi\r\n\r\n"
            "2\r\n0:00:03,00 --> 0:00:04,0\r\nShort forms\r\n"
        )
        cues = parse_srt(raw)
        assert len(cues) == 2
        assert cues[1].start_ms == 3000  # '00' millis padded, 1-digit hour ok

    def test_parse_without_block_indexes(self):
        cues = parse_srt("00:00:01,000 --> 00:00:02,000\nNo index line\n")
        assert len(cues) == 1
        assert cues[0].text == "No index line"

    def test_parse_rejects_garbage(self):
        with pytest.raises(SrtImportError):
            parse_srt("this is not a subtitle file\nat all\n\n")
        with pytest.raises(SrtImportError):
            parse_srt("")
        # end <= start and empty text blocks are skipped; none valid -> error
        with pytest.raises(SrtImportError):
            parse_srt("1\n00:00:05,000 --> 00:00:02,000\nbackwards\n")

    def test_decode_cp874_thai(self):
        thai = "สวัสดี".encode("cp874")
        assert decode_srt_bytes(thai) == "สวัสดี"
        assert decode_srt_bytes(b"hello") == "hello"
        assert decode_srt_bytes(b"\xef\xbb\xbfhello") == "hello"  # BOM stripped

    def test_normalise_roundtrip(self):
        text, count = normalise_srt(self.VALID.encode("utf-8"))
        assert count == 2
        assert text.startswith("1\n00:00:01,000 --> 00:00:03,500\n")
        assert "สวัสดี" in normalise_srt(
            "1\n00:00:01,000 --> 00:00:02,000\nสวัสดี\n".encode("cp874")
        )[0]


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

    def test_ass_format_uses_ass_filter_without_force_style(self, tmp_path: Path):
        paths = (tmp_path / "v.mp4", tmp_path / "render.ass", tmp_path / "o.mp4")
        args = build_burn_args(*paths, subtitle_format="ass", font_name="Tahoma")
        filter_value = args[args.index("-vf") + 1]
        assert filter_value == "ass=render.ass"  # style lives in the file header
        assert "force_style" not in filter_value

    def test_ass_rejects_the_srt_name_and_vice_versa(self, tmp_path: Path):
        with pytest.raises(ValueError):
            build_burn_args(
                tmp_path / "v.mp4",
                tmp_path / "render.srt",
                tmp_path / "o.mp4",
                subtitle_format="ass",
            )
        with pytest.raises(ValueError):
            build_burn_args(
                tmp_path / "v.mp4",
                tmp_path / "render.ass",
                tmp_path / "o.mp4",
                subtitle_format="srt",
            )


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
            data={"font_name": "Tahoma"},
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
    def test_styled_ass_render_lifecycle(
        self, client, completed_job_id, manual_render_manager, clean_renders
    ):
        created = client.post(
            f"/api/v1/jobs/{completed_job_id}/render",
            data={
                "subtitle_format": "ass",
                "font_name": "Leelawadee UI",
                "font_size": "56",
                "primary_color": "00FFFF",
                "outline": "3",
                "margin_v": "80",
                "position": "top",
            },
        )
        assert created.status_code == 201, created.text
        render_id = created.json()["render_id"]

        assert manual_render_manager.process_once() == render_id
        done = client.get(f"/api/v1/renders/{render_id}").json()
        assert done["status"] == "completed"
        assert done["subtitle_format"] == "ass"

        # the burner burned an ASS file carrying the requested style
        call = manual_render_manager._burner.calls[0]
        assert call["subtitle_format"] == "ass"
        ass_path = Path(call["srt_path"])
        assert ass_path.name == "render.ass"
        content = ass_path.read_text(encoding="utf-8")
        assert content.startswith("[Script Info]")
        assert "Style: Default,Leelawadee UI,56,&H00FFFF00" in content
        assert ",3,0,8,10,10,80,1" in content  # outline, shadow, alignment, margins
        # PlayRes is set from the media dimensions (not the 1920x1080 default)
        assert "PlayResX:" in content and "PlayResY:" in content

    @requires_ffmpeg
    def test_plain_render_with_position_upgrades_to_ass(
        self, client, completed_job_id, manual_render_manager, clean_renders
    ):
        """A positioned plain SRT render burns through a generated ASS -
        force_style Alignment is not portable (SSA-v4 semantics), so the
        position is baked into a minimal v4+ style instead."""
        created = client.post(
            f"/api/v1/jobs/{completed_job_id}/render",
            data={"position": "top"},
        )
        assert created.status_code == 201, created.text
        render_id = created.json()["render_id"]

        assert manual_render_manager.process_once() == render_id
        done = client.get(f"/api/v1/renders/{render_id}").json()
        assert done["status"] == "completed"
        assert done["subtitle_format"] == "srt"  # the user's choice is echoed

        call = manual_render_manager._burner.calls[0]
        assert call["subtitle_format"] == "ass"  # internally upgraded
        ass_path = Path(call["srt_path"])
        assert ass_path.name == "render.ass"
        content = ass_path.read_text(encoding="utf-8")
        assert content.startswith("[Script Info]")
        assert "ScriptType: v4.00+" in content
        # Alignment=8 (top-center); the default outline/margin scale with the
        # 320x240 sample (defaults are defined at 1080p): 1 / 9
        assert ",1,0,8,10,10,9,1" in content

    def test_styled_render_validation(self, client, completed_job_id, clean_renders):
        # unknown format
        response = client.post(
            f"/api/v1/jobs/{completed_job_id}/render", data={"subtitle_format": "ssa"}
        )
        assert response.status_code == 400
        # invalid colour
        response = client.post(
            f"/api/v1/jobs/{completed_job_id}/render",
            data={"subtitle_format": "ass", "primary_color": "rainbow"},
        )
        assert response.status_code == 400
        assert "colour" in response.json()["detail"]
        # invalid position
        response = client.post(
            f"/api/v1/jobs/{completed_job_id}/render",
            data={"subtitle_format": "ass", "position": "diagonal"},
        )
        assert response.status_code == 400
        # external files are SRT-only for now
        response = client.post(
            f"/api/v1/jobs/{completed_job_id}/render",
            data={"subtitle_format": "ass"},
            files={"srt_file": ("subs.srt", b"1\n00:00:01,000 --> 00:00:02,000\nhi\n")},
        )
        assert response.status_code == 400

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


class TestExternalSrt:
    EXTERNAL_SRT = (
        b"1\n00:00:00,200 --> 00:00:01,800\nExternal one\n\n"
        b"2\n00:00:01,900 --> 00:00:03,500\nExternal two\n"
    )

    @requires_ffmpeg
    def test_render_with_external_srt(
        self, client, completed_job_id, manual_render_manager, clean_renders
    ):
        created = client.post(
            f"/api/v1/jobs/{completed_job_id}/render",
            files={"srt_file": ("external.srt", self.EXTERNAL_SRT, "text/plain")},
            data={"font_name": "Tahoma"},
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["source"] == "external"
        assert body["subtitle_count"] == 2
        render_id = body["render_id"]

        assert manual_render_manager.process_once() == render_id
        done = client.get(f"/api/v1/renders/{render_id}").json()
        assert done["status"] == "completed"
        assert done["source"] == "external"

        # the burner burned the uploaded (normalised) SRT, not the DB rows
        call = manual_render_manager._burner.calls[0]
        staged = Path(call["srt_path"]).read_text(encoding="utf-8")
        assert "External one" in staged
        assert "External two" in staged

    def test_external_srt_skips_completed_check(self, client, media_id, clean_renders):
        # a queued (not completed) job + external SRT is allowed
        job_id = client.post(
            "/api/v1/jobs", json={"media_id": media_id, "model": "tiny"}
        ).json()["job_id"]
        created = client.post(
            f"/api/v1/jobs/{job_id}/render",
            files={"srt_file": ("external.srt", self.EXTERNAL_SRT, "text/plain")},
        )
        assert created.status_code == 201, created.text
        assert created.json()["source"] == "external"

    def test_rejects_bad_srt(self, client, completed_job_id, clean_renders):
        response = client.post(
            f"/api/v1/jobs/{completed_job_id}/render",
            files={"srt_file": ("bad.srt", b"not a subtitle file", "text/plain")},
        )
        assert response.status_code == 400
        assert "cues" in response.json()["detail"]

    def test_rejects_wrong_extension(self, client, completed_job_id, clean_renders):
        response = client.post(
            f"/api/v1/jobs/{completed_job_id}/render",
            files={"srt_file": ("subs.vtt", b"WEBVTT\n\n00:01.000 --> 00:02.000\nx\n",
                                "text/vtt")},
        )
        assert response.status_code == 400
        assert ".srt" in response.json()["detail"]

    @requires_ffmpeg
    def test_editor_source_uses_db_rows(
        self, client, completed_job_id, manual_render_manager, clean_renders
    ):
        created = client.post(f"/api/v1/jobs/{completed_job_id}/render")
        assert created.status_code == 201, created.text
        assert created.json()["source"] == "editor"
        assert created.json()["subtitle_count"] == 1  # from the fake engine


class TestImportSubtitles:
    """Import an external .srt into the editor (preview + edit like AI subs)."""

    IMPORTED = (
        b"1\n00:00:00,100 --> 00:00:01,500\nImported line one\n\n"
        b"2\n00:00:02,000 --> 00:00:04,000\nImported line two\nspans two lines\n"
    )

    def _upload(self, client, job_id, content=IMPORTED, name="imported.srt"):
        return client.post(
            f"/api/v1/jobs/{job_id}/subtitles/import",
            files={"srt_file": (name, content, "text/plain")},
        )

    @requires_ffmpeg
    def test_import_replaces_editor_rows(self, client, completed_job_id):
        response = self._upload(client, completed_job_id)
        assert response.status_code == 200, response.text
        assert response.json()["subtitles"] == 2

        rows = client.get(f"/api/v1/jobs/{completed_job_id}/subtitles").json()
        assert len(rows) == 2
        assert rows[0]["text"] == "Imported line one"
        assert rows[0]["start_ms"] == 100 and rows[0]["end_ms"] == 1500
        assert rows[0]["is_edited"] is False
        assert rows[1]["text"] == "Imported line two\nspans two lines"

        # on-disk SRT regenerated with the imported cues
        srt = (
            get_settings().storage_subdir("subtitles")
            / completed_job_id
            / "output.srt"
        )
        content = srt.read_text(encoding="utf-8")
        assert "Imported line one" in content
        assert "Imported line two" in content

    @requires_ffmpeg
    def test_imported_rows_feed_editor_source_render(
        self, client, completed_job_id, manual_render_manager, clean_renders
    ):
        assert self._upload(client, completed_job_id).status_code == 200
        render_id = client.post(
            f"/api/v1/jobs/{completed_job_id}/render"
        ).json()["render_id"]
        assert manual_render_manager.process_once() == render_id
        assert client.get(f"/api/v1/renders/{render_id}").json()["status"] == "completed"

        call = manual_render_manager._burner.calls[0]
        staged = Path(call["srt_path"]).read_text(encoding="utf-8")
        assert "Imported line one" in staged

    def test_import_rejects_bad_files(self, client, completed_job_id):
        garbage = self._upload(client, completed_job_id, b"nothing here")
        assert garbage.status_code == 400
        assert "cues" in garbage.json()["detail"]

        wrong_ext = self._upload(
            client, completed_job_id, b"x", name="subs.vtt"
        )
        assert wrong_ext.status_code == 400

    def test_import_unknown_job_404(self, client):
        assert self._upload(client, "nope").status_code == 404


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

    @requires_ffmpeg
    def test_position_actually_moves_the_subtitles(
        self, client, completed_job_id, clean_renders
    ):
        """The position choice must show up in real pixels: render the same
        job bottom (default) and top, then locate the differing rows in a
        frame from the middle of the cue - the text must move across the
        mid-line. (force_style Alignment means SSA-v4 values for SRT, which
        is why positioned burns go through a generated ASS instead.)"""
        import subprocess as sp

        from conftest import FFMPEG

        from app.services.render.burner import SubtitleBurner

        def gray_frame(path: Path) -> bytes:
            proc = sp.run(  # noqa: S603 - fixed argv, no shell
                [
                    FFMPEG, "-y", "-v", "error", "-ss", "1.5", "-i", str(path),
                    "-frames:v", "1", "-vf", "scale=64:48",
                    "-f", "rawvideo", "-pix_fmt", "gray", "-",
                ],
                check=True,
                capture_output=True,
            )
            return proc.stdout

        manager = ManualManager(burner=SubtitleBurner())
        set_render_manager(manager)
        try:
            outputs: dict[str, Path] = {}
            for label, form in (
                ("bottom", {}),
                ("top", {"position": "top"}),
            ):
                render_id = client.post(
                    f"/api/v1/jobs/{completed_job_id}/render", data=form
                ).json()["render_id"]
                assert manager.process_once() == render_id
                done = client.get(f"/api/v1/renders/{render_id}").json()
                assert done["status"] == "completed", done
                outputs[label] = (
                    get_settings().storage_subdir("renders") / render_id / "output.mp4"
                )

            bottom = gray_frame(outputs["bottom"])
            top = gray_frame(outputs["top"])
            assert len(bottom) == 64 * 48 and len(top) == 64 * 48

            hot_rows: list[int] = []
            for y in range(48):
                row_diff = max(
                    abs(a - b)
                    for a, b in zip(
                        bottom[y * 64 : (y + 1) * 64],
                        top[y * 64 : (y + 1) * 64],
                        strict=True,
                    )
                )
                if row_diff > 30:  # subtitle text; encoder ripple stays below
                    hot_rows.append(y)

            assert hot_rows, "the two renders differ nowhere - no subtitle burned?"
            assert min(hot_rows) < 24, f"text never reached the top half: {hot_rows}"
            assert max(hot_rows) >= 24, f"text never left the bottom half: {hot_rows}"
        finally:
            set_render_manager(None)
