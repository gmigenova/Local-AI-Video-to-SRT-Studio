"""Phase 5 tests: line-aware packing, VAD params, metrics, retention."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.maintenance.retention import RetentionService
from app.services.subtitle.processor import SubtitleProcessor
from app.services.transcription.engine import (
    TranscribedSegment,
    TranscriptionOptions,
    WordTiming,
    normalize_text,
)
from app.services.transcription.faster_whisper_engine import FasterWhisperEngine
from app.services.transcription.metrics import (
    character_error_rate,
    levenshtein,
    word_error_rate,
)


def make_words(tokens: list[str], start_ms: int, ms_per_word: int = 500):
    cursor = start_ms
    words = []
    for token in tokens:
        words.append(WordTiming(cursor, cursor + ms_per_word, token, 0.95))
        cursor += ms_per_word
    return words


class TestLineAwarePacking:
    def test_three_line_overflow_split_into_two_line_chunks(self):
        """The Phase-1 smoke case: 82 chars fit the 84-char budget but wrap
        to 3 lines — packing must split by wrapped line count, not chars."""
        tokens = (
            " Today we will learn about artificial intelligence and local video transcription.".split()
        )
        tokens = [" " + t for t in tokens]  # whisper-style leading spaces
        text = normalize_text("".join(tokens))
        segment = TranscribedSegment(
            0, 6000, text, make_words(tokens, 0, ms_per_word=700)
        )
        result = SubtitleProcessor().process([segment])
        assert len(result.subtitles) >= 2
        codes = {w.code for w in result.warnings}
        assert "TOO_MANY_LINES" not in codes
        for sub in result.subtitles:
            assert sub.text.count("\n") + 1 <= 2

    def test_merge_respects_wrapped_lines(self):
        """Two fragments that fit the char budget but wrap to 3 lines must
        not merge (greedy wrap can only fit 2 lines when boundaries align)."""
        a = "Today we will learn about artificial intelligence"  # 49 chars
        b = "and local video transcription."  # 30 chars; the trailing period
        # pushes the combined wrap to 43 chars on line 2 -> 3 lines total
        seg_a = TranscribedSegment(0, 1500, a, make_words([" " + a], 0))
        seg_b = TranscribedSegment(1550, 3000, b, make_words([" " + b], 1550))
        result = SubtitleProcessor().process([seg_a, seg_b])
        assert len(result.subtitles) == 2

    def test_normal_merges_still_work(self):
        seg_a = TranscribedSegment(0, 500, "Hello", make_words([" Hello"], 0))
        seg_b = TranscribedSegment(600, 1100, "there", make_words([" there"], 600))
        result = SubtitleProcessor().process([seg_a, seg_b])
        assert len(result.subtitles) == 1

    def test_split_tail_keeps_word_timing_and_min_duration(self):
        """Regression: the 2nd chunk of a split must start at its own first
        word (not the parent segment start) and still receive the
        min-duration extension."""
        tokens = [" Today", " we", " will", " learn", " about", " artificial",
                  " intelligence", " and", " local", " video", " transcription."]
        words, cursor = [], 3980
        for token in tokens:
            duration = 640 if token != " transcription." else 570
            words.append(WordTiming(cursor, cursor + duration, token, 0.95))
            cursor += duration + (620 if token == " video" else 50)
        text = normalize_text("".join(tokens))
        result = SubtitleProcessor().process(
            [TranscribedSegment(3980, 8040, text, tuple(words))]
        )
        assert len(result.subtitles) == 2
        tail = result.subtitles[1]
        assert tail.text == "transcription."
        assert tail.start_ms >= 10_000  # own word timing, not the segment start
        assert tail.duration_ms >= 800  # min-duration applied after the split
        codes = {w.code for w in result.warnings}
        assert "TOO_SHORT" not in codes
        assert "TOO_MANY_LINES" not in codes


class TestVadParameters:
    @staticmethod
    def _capturing_model(captured: dict):
        from types import SimpleNamespace

        class _CapturingModel:
            def transcribe(self, audio, language=None, task="transcribe",
                           beam_size=5, vad_filter=False, vad_parameters=None):
                captured.update(
                    {
                        k: v
                        for k, v in {
                            "language": language,
                            "task": task,
                            "beam_size": beam_size,
                            "vad_filter": vad_filter,
                            "vad_parameters": vad_parameters,
                        }.items()
                    }
                )
                info = SimpleNamespace(
                    language="en", language_probability=0.9, duration=1.0
                )
                return iter(()), info

        return _CapturingModel()

    def test_vad_params_forwarded_when_supported(self):
        captured: dict = {}
        engine = FasterWhisperEngine("tiny")
        engine._model = self._capturing_model(captured)
        options = TranscriptionOptions(
            vad_filter=True, vad_threshold=0.35, vad_min_silence_ms=2500
        )
        result = engine.transcribe(Path("unused.wav"), options)
        assert result.language == "en"
        assert captured["vad_filter"] is True
        assert captured["vad_parameters"] == {
            "threshold": 0.35,
            "min_silence_duration_ms": 2500,
        }

    def test_vad_params_omitted_when_not_set(self):
        captured: dict = {}
        engine = FasterWhisperEngine("tiny")
        engine._model = self._capturing_model(captured)
        engine.transcribe(Path("unused.wav"), TranscriptionOptions())
        assert "vad_parameters" not in captured or captured["vad_parameters"] is None


class TestMetrics:
    def test_levenshtein(self):
        assert levenshtein(list("kitten"), list("sitting")) == 3
        assert levenshtein(["a", "b"], ["a", "b"]) == 0
        assert levenshtein([], ["a"]) == 1

    def test_wer_identical(self):
        assert word_error_rate("Hello world", "Hello world!") == 0.0

    def test_wer_known_edits(self):
        # ref: the cat sat ; hyp: the cat sat on
        assert word_error_rate("the cat sat", "the cat sat on") == pytest.approx(1 / 3)

    def test_cer_thai(self):
        ref = "สวัสดีครับ"  # 10 chars incl. combining marks
        assert character_error_rate(ref, ref) == 0.0
        # dropping "ครับ" (4 chars incl. a combining mark) -> 4/10
        assert character_error_rate(ref, "สวัสดี") == pytest.approx(0.4, abs=0.01)

    def test_cer_ignores_punctuation_and_case(self):
        assert character_error_rate("Hello, world!", "hello world") == 0.0

    def test_empty_reference(self):
        assert word_error_rate("", "something") == 1.0
        assert word_error_rate("", "") == 0.0


class TestRetention:
    def _settings(self, tmp_path: Path, **overrides) -> Settings:
        values = {
            "storage_path": tmp_path / "storage",
            "retention_temp_days": 7,
            "retention_audio_days": 14,
            "retention_artifact_days": 0,
            **overrides,
        }
        return Settings(_env_file=None, **values)  # type: ignore[arg-type]

    def _touch(self, path: Path, age_days: float) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
        stamp = time.time() - age_days * 86_400
        import os

        os.utime(path, (stamp, stamp))
        # retention ages directories, so stamp the containing dir too
        os.utime(path.parent, (stamp, stamp))

    def test_temp_cleaned_after_retention(self, tmp_path):
        settings = self._settings(tmp_path)
        old = settings.storage_subdir("temp") / "old-job"
        fresh = settings.storage_subdir("temp") / "fresh-job"
        self._touch(old / "extracted.wav", age_days=10)
        self._touch(fresh / "extracted.wav", age_days=1)
        removed = RetentionService(settings).cleanup_temp()
        assert removed == 1
        assert not old.exists()
        assert fresh.exists()

    def test_temp_retention_disabled(self, tmp_path):
        settings = self._settings(tmp_path, retention_temp_days=0)
        old = settings.storage_subdir("temp") / "old"
        self._touch(old / "f.wav", age_days=365)
        assert RetentionService(settings).cleanup_temp() == 0
        assert old.exists()

    def test_audio_of_completed_jobs_cleaned(self, tmp_path):
        from app.core.config import get_settings
        from app.database.base import init_database
        from app.models.job import JobStatus
        from app.repositories.jobs import JobsRepository
        from app.repositories.media import MediaRepository
        from app.repositories.projects import ProjectsRepository

        settings = self._settings(tmp_path)
        original_url = get_settings().database_url
        init_database(
            f"sqlite:///{(tmp_path / 'retention.db').as_posix()}", create_tables=True
        )
        factory = init_database()  # ensure global points at the temp db

        db = factory()
        try:
            project = ProjectsRepository(db).create("p")
            media = MediaRepository(db).create(
                project_id=project.id, original_name="v.mp4",
                stored_name="v.mp4", file_path="x", audio_stream_index=0,
            )
            done = JobsRepository(db).create(media.id, "tiny", None, {})
            JobsRepository(db).update_status(done.id, JobStatus.COMPLETED)
            queued = JobsRepository(db).create(media.id, "tiny", None, {})

            old_dir = settings.storage_subdir("audio") / done.id
            active_dir = settings.storage_subdir("audio") / queued.id
            self._touch(old_dir / "extracted.wav", age_days=20)
            self._touch(active_dir / "extracted.wav", age_days=20)

            # uploads are never touched by retention
            upload_dir = settings.storage_subdir("uploads") / media.id
            self._touch(upload_dir / "original.mp4", age_days=365)

            removed = RetentionService(settings).cleanup_audio(db)
            assert removed == 1
            assert not old_dir.exists()
            assert active_dir.exists()  # job not completed
            assert upload_dir.exists()  # source video kept
        finally:
            db.close()
            # restore the suite-wide database for subsequent tests
            init_database(original_url, create_tables=True)

    def test_artifacts_kept_by_default(self, tmp_path):
        settings = self._settings(tmp_path)  # retention_artifact_days = 0
        entry = settings.storage_subdir("subtitles") / "some-job"
        self._touch(entry / "output.srt", age_days=365)
        from app.database.base import get_session_factory

        db = get_session_factory()()
        try:
            assert RetentionService(settings).cleanup_artifacts(db) == 0
            assert entry.exists()
        finally:
            db.close()
