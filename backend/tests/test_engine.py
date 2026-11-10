"""Tests for the transcription engine layer (no GPU / model download needed)."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.errors import ModelLoadError, OperationCancelled
from app.services.transcription.engine import TranscriptionOptions
from app.services.transcription.faster_whisper_engine import (
    FasterWhisperEngine,
    resolve_inference_target,
)


class _LimitedFakeModel:
    """Mimics an installed faster-whisper version with a reduced API."""

    def transcribe(self, audio, language=None, task="transcribe", beam_size=5, vad_filter=False):
        raise AssertionError("not called in this test")


class TestParameterFiltering:
    def test_unsupported_parameters_are_dropped(self):
        engine = FasterWhisperEngine("tiny")
        engine._model = _LimitedFakeModel()
        options = TranscriptionOptions(
            language=None,  # auto-detect: must not be forwarded as None override
            beam_size=5,
            best_of=5,
            word_timestamps=True,
            condition_on_previous_text=True,
            temperature=0.0,
            initial_prompt=None,
        )
        kwargs = engine._supported_transcribe_kwargs(options)
        assert set(kwargs) == {"task", "beam_size", "vad_filter"}
        assert kwargs["task"] == "transcribe"

    def test_supported_parameters_kept(self):
        engine = FasterWhisperEngine("tiny")
        engine._model = _LimitedFakeModel()
        options = TranscriptionOptions(language="th", beam_size=1, vad_filter=False)
        kwargs = engine._supported_transcribe_kwargs(options)
        assert kwargs["language"] == "th"
        assert kwargs["beam_size"] == 1
        assert kwargs["vad_filter"] is False


class TestResolveInferenceTarget:
    def test_cpu_auto(self):
        device, compute, note = resolve_inference_target("cpu", "auto")
        assert (device, compute, note) == ("cpu", "int8", None)

    def test_explicit_compute_type_kept(self):
        device, compute, _ = resolve_inference_target("cpu", "int8_float16")
        assert (device, compute) == ("cpu", "int8_float16")

    def test_unknown_device_rejected(self):
        with pytest.raises(ModelLoadError):
            resolve_inference_target("tpu", "auto")

    def test_cuda_falls_back_when_unavailable(self):
        pytest.importorskip("ctranslate2")
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            pytest.skip("CUDA available: fallback path not testable")
        device, compute, note = resolve_inference_target("cuda", "auto")
        assert device == "cpu"
        assert note is not None


class TestCancellation:
    def test_transcribe_cancelled_mid_stream(self):
        cancel = threading.Event()

        def segment_gen():
            for i in range(5):
                yield SimpleNamespace(
                    start=float(i),
                    end=float(i + 1),
                    text=f"word {i}",
                    words=None,
                    id=i,
                    seek=0,
                    avg_logprob=0.0,
                    compression_ratio=1.0,
                    no_speech_prob=0.0,
                    temperature=0.0,
                )
                cancel.set()  # set after the first segment was produced

        class _CancellingModel:
            def transcribe(self, audio, **kwargs):
                info = SimpleNamespace(
                    language="en", language_probability=0.99, duration=5.0
                )
                return segment_gen(), info

        engine = FasterWhisperEngine("tiny")
        engine._model = _CancellingModel()
        with pytest.raises(OperationCancelled):
            engine.transcribe(
                Path("unused.wav"), TranscriptionOptions(), cancel_event=cancel
            )

    def test_empty_text_segments_skipped(self):
        def gen():
            for text in ("", "   ", "real text"):
                yield SimpleNamespace(
                    start=0.0, end=1.5, text=text, words=None, id=0, seek=0,
                    avg_logprob=0.0, compression_ratio=1.0,
                    no_speech_prob=0.0, temperature=0.0,
                )

        class _Model:
            def transcribe(self, audio, **kwargs):
                info = SimpleNamespace(language="en", language_probability=0.9, duration=5.0)
                return gen(), info

        engine = FasterWhisperEngine("tiny")
        engine._model = _Model()
        result = engine.transcribe(Path("unused.wav"), TranscriptionOptions())
        assert len(result.segments) == 1
        assert result.segments[0].text == "real text"
        assert result.language == "en"
        assert result.duration_ms == 5000

    def test_transcribe_requires_loaded_model(self):
        engine = FasterWhisperEngine("tiny")
        from app.core.errors import TranscriptionError

        with pytest.raises(TranscriptionError):
            engine.transcribe(Path("x.wav"), TranscriptionOptions())
