"""End-to-end pipeline tests with a fake transcription engine (18.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import requires_ffmpeg

from app.core.config import Settings
from app.pipeline import TranscriptionPipeline
from app.services.transcription.engine import (
    TranscribedSegment,
    TranscriptionEngine,
    TranscriptionOptions,
    TranscriptionResult,
    WordTiming,
)


class FakeEngine(TranscriptionEngine):
    def __init__(self) -> None:
        self._loaded = False
        self.calls: list[str] = []

    @property
    def model_name(self) -> str:
        return "fake-model"

    def load_model(self) -> None:
        self._loaded = True

    def is_loaded(self) -> bool:
        return self._loaded

    def unload_model(self) -> None:
        self._loaded = False

    def transcribe(self, audio_path, options, progress_callback=None, cancel_event=None):
        assert Path(audio_path).exists(), "engine must receive the extracted wav"
        self.calls.append(str(audio_path))
        if progress_callback:
            progress_callback(0.5, "Transcribing audio")
        words = (
            WordTiming(1200, 1500, " Hello", 0.99),
            WordTiming(1500, 3500, " world.", 0.98),
        )
        segment = TranscribedSegment(1200, 3500, "Hello world.", words, 0.985)
        return TranscriptionResult("en", 0.97, 2300, (segment,))


class FakeManager:
    def __init__(self, engine: FakeEngine) -> None:
        self.engine = engine

    def get_engine(self, model_name=None, device=None, compute_type=None):
        return self.engine


@pytest.fixture()
def pipeline() -> TranscriptionPipeline:
    settings = Settings(_env_file=None)  # isolated from any local .env
    return TranscriptionPipeline(
        settings=settings,
        model_manager=FakeManager(FakeEngine()),  # type: ignore[arg-type]
    )


class TestPipeline:
    def test_unknown_format_rejected(self, pipeline, tmp_path, sample_video):
        from app.core.errors import ExportError

        with pytest.raises(ExportError):
            pipeline.run(sample_video, export_formats=["docx"], work_dir=tmp_path / "w")

    @requires_ffmpeg
    def test_full_run_produces_exports(self, pipeline, sample_video, tmp_path):
        progress_calls: list[float] = []

        result = pipeline.run(
            video_path=sample_video,
            options=TranscriptionOptions(model="fake-model"),
            work_dir=tmp_path / "work",
            output_dir=tmp_path / "out",
            export_formats=["srt", "vtt", "txt", "json"],
            progress=lambda fraction, stage: progress_calls.append(fraction),
        )

        # media inspected
        assert result.media_info.has_audio
        # transcription output persisted as raw transcript
        assert result.transcript_path is not None
        payload = json.loads(result.transcript_path.read_text(encoding="utf-8"))
        assert payload["language"] == "en"
        assert payload["segments"][0]["words"][0]["word"] == " Hello"
        # subtitles generated and exported
        assert len(result.subtitles) == 1
        assert result.subtitles[0].text == "Hello world."
        for fmt in ("srt", "vtt", "txt", "json"):
            assert (tmp_path / "out" / f"output.{fmt}").is_file(), fmt
        srt_content = (tmp_path / "out" / "output.srt").read_text(encoding="utf-8")
        assert "00:00:01,200 --> 00:00:03,500" in srt_content
        assert "Hello world." in srt_content
        # progress reported monotonically up to 1.0
        assert progress_calls == sorted(progress_calls)
        assert abs(progress_calls[-1] - 1.0) < 1e-6

    @requires_ffmpeg
    def test_default_format_is_srt_only(self, pipeline, sample_video, tmp_path):
        result = pipeline.run(
            video_path=sample_video,
            work_dir=tmp_path / "work",
            output_dir=tmp_path / "out",
        )
        assert list(result.export_paths) == ["srt"]
