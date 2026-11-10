"""Integration tests for FFprobe inspection and FFmpeg extraction (18.2)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from conftest import requires_ffmpeg

from app.core.errors import (
    FFmpegExecutionError,
    MediaValidationError,
    OperationCancelled,
    UnsupportedFileTypeError,
)
from app.services.media.audio_extractor import AudioExtractor
from app.services.media.ffprobe import (
    is_supported_video_file,
    probe_video,
)


class TestValidation:
    def test_supported_extensions(self, tmp_path):
        for name in ("a.mp4", "b.MKV", "c.webm", "d.mov", "e.m4v", "f.avi"):
            assert is_supported_video_file(tmp_path / name)
        assert not is_supported_video_file(tmp_path / "g.xyz")
        assert not is_supported_video_file(tmp_path / "noext")

    def test_missing_file_rejected(self, tmp_path):
        with pytest.raises(MediaValidationError):
            probe_video(tmp_path / "missing.mp4")

    def test_unsupported_extension_rejected(self, tmp_path):
        target = tmp_path / "movie.xyz"
        target.write_bytes(b"junk")
        with pytest.raises(UnsupportedFileTypeError):
            probe_video(target)

    def test_empty_file_rejected(self, tmp_path):
        target = tmp_path / "empty.mp4"
        target.touch()
        with pytest.raises(MediaValidationError):
            probe_video(target)


@pytest.mark.usefixtures("sample_video")
class TestProbe:
    @requires_ffmpeg
    def test_probe_real_video(self, sample_video: Path):
        info = probe_video(sample_video)
        assert info.has_audio
        assert len(info.audio_streams) >= 1
        assert info.video_codec == "h264"
        assert info.width == 320 and info.height == 240
        assert info.duration_ms is not None
        assert abs(info.duration_ms - 2000) < 300
        assert info.default_audio_stream() is not None


class TestAudioExtraction:
    @requires_ffmpeg
    def test_extracts_16k_mono_wav(self, sample_video: Path, tmp_path: Path):
        extractor = AudioExtractor()
        out = tmp_path / "audio.wav"
        result = extractor.extract(sample_video, out)
        assert out.is_file()
        assert out.stat().st_size > 44
        # 16 kHz mono s16le: ~64 KB per second -> ~2s of audio
        assert 1.5 <= result.duration_ms / 1000 <= 2.5

    @requires_ffmpeg
    def test_bad_stream_index_raises(self, sample_video: Path, tmp_path: Path):
        extractor = AudioExtractor()
        with pytest.raises(FFmpegExecutionError):
            extractor.extract(sample_video, tmp_path / "a.wav", audio_stream_index=9)

    @requires_ffmpeg
    def test_cancelled_before_start(self, sample_video: Path, tmp_path: Path):
        extractor = AudioExtractor()
        cancel = threading.Event()
        cancel.set()
        with pytest.raises(OperationCancelled):
            extractor.extract(sample_video, tmp_path / "a.wav", cancel_event=cancel)
        assert not (tmp_path / "a.wav").exists()

    @requires_ffmpeg
    def test_missing_ffmpeg_raises(self, sample_video: Path, tmp_path: Path):
        extractor = AudioExtractor(ffmpeg_path="definitely-not-ffmpeg-xyz")
        from app.core.errors import FFmpegNotFoundError

        with pytest.raises(FFmpegNotFoundError):
            extractor.extract(sample_video, tmp_path / "a.wav")
