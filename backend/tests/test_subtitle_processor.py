"""Tests for the subtitle processing engine (section 6, 18.1)."""

from __future__ import annotations

from app.services.subtitle.processor import SubtitleProcessor, SubtitleRules
from app.services.transcription.engine import (
    TranscribedSegment,
    WordTiming,
    normalize_text,
)


def make_words(tokens: list[str], start_ms: int, ms_per_word: int = 400):
    words = []
    cursor = start_ms
    for token in tokens:
        words.append(WordTiming(cursor, cursor + ms_per_word, token, 0.95))
        cursor += ms_per_word
    return tuple(words)


def make_segment(
    start_ms: int, end_ms: int, text: str, tokens: list[str] | None = None,
    ms_per_word: int = 400,
) -> TranscribedSegment:
    words = make_words(tokens, start_ms, ms_per_word) if tokens else ()
    return TranscribedSegment(start_ms, end_ms, normalize_text(text), words)


def process(segments, rules=None):
    return SubtitleProcessor(rules).process(segments)


def codes(warnings):
    return {w.code for w in warnings}


class TestNormalization:
    def test_empty_and_whitespace_segments_removed(self):
        result = process(
            [make_segment(0, 1000, ""), make_segment(1000, 2000, "   "), make_segment(2000, 3000, "Real.")]
        )
        assert len(result.subtitles) == 1
        assert result.subtitles[0].text == "Real."

    def test_text_whitespace_collapsed(self):
        result = process([make_segment(0, 1000, "  hello   world  ")])
        assert result.subtitles[0].text == "hello world"

    def test_invalid_timestamp_repaired(self):
        result = process([make_segment(1000, 500, "Broken")])
        sub = result.subtitles[0]
        assert sub.start_ms == 1000
        assert sub.end_ms == 1800  # 200ms slice, then extended to min duration


class TestMerging:
    def test_adjacent_tiny_fragments_merge(self):
        result = process(
            [make_segment(0, 500, "Hello"), make_segment(600, 1100, "there")]
        )
        assert len(result.subtitles) == 1
        assert result.subtitles[0].text == "Hello there"
        assert result.subtitles[0].start_ms == 0
        assert result.subtitles[0].end_ms == 1100

    def test_no_merge_across_sentence_boundary(self):
        result = process(
            [make_segment(0, 500, "Hello there."), make_segment(600, 1100, "Next")]
        )
        assert len(result.subtitles) == 2

    def test_no_merge_when_combined_too_long(self):
        long_text = " ".join(["word"] * 20)  # 100 chars > 84 total
        result = process(
            [make_segment(0, 500, long_text), make_segment(600, 1100, "more text")]
        )
        assert len(result.subtitles) == 2

    def test_no_merge_across_large_gap(self):
        result = process(
            [make_segment(0, 900, "First one"), make_segment(5000, 6000, "Much later")]
        )
        assert len(result.subtitles) == 2


class TestSplitting:
    def test_long_segment_split_by_duration(self):
        tokens = [f" word{i:02d}" for i in range(20)]  # 20 * 600ms = 12s
        text = normalize_text("".join(tokens))
        result = process([make_segment(0, 12000, text, tokens, ms_per_word=600)])
        assert len(result.subtitles) >= 2
        assert all(s.duration_ms <= 7000 + 600 for s in result.subtitles)
        # no word lost or reordered
        original_tokens = [t.strip() for t in tokens]
        produced_tokens = [w for s in result.subtitles for w in s.text.split()]
        assert produced_tokens == original_tokens

    def test_prefers_sentence_boundaries(self):
        tokens = (
            [" This", " is", " the", " first", " sentence."]
            + [f" filler{k}" for k in range(12)]
            + [" End", " two."]
        )
        text = normalize_text("".join(tokens))
        result = process([make_segment(0, 600, text, tokens, ms_per_word=600)])
        if len(result.subtitles) >= 2:
            first = result.subtitles[0].text
            assert first.endswith("sentence.") or first.endswith(".")

    def test_long_segment_without_words_stays_intact_with_warning(self):
        result = process([make_segment(0, 10000, "A long narration without word timings")])
        assert len(result.subtitles) == 1
        assert "TOO_LONG_DURATION" in codes(result.warnings)


class TestTimingRules:
    def test_min_duration_extension(self):
        result = process(
            [make_segment(0, 300, "Hi."), make_segment(2000, 3000, "Next one.")]
        )
        assert result.subtitles[0].end_ms - result.subtitles[0].start_ms >= 800

    def test_extension_never_creates_overlap(self):
        result = process(
            [make_segment(0, 300, "Hi."), make_segment(700, 1700, "Neighbor")]
        )
        first, second = result.subtitles
        # extended at most to second.start - gap
        assert first.end_ms <= second.start_ms - 50

    def test_overlapping_inputs_separated(self):
        long_a = "A" * 50
        long_b = "B" * 50
        result = process(
            [make_segment(0, 1000, long_a), make_segment(900, 2000, long_b)]
        )
        first, second = result.subtitles
        assert second.start_ms >= first.end_ms + 50
        assert "OVERLAP" not in codes(result.warnings)
        assert "INVALID_TIMESTAMP" not in codes(result.warnings)

    def test_indices_sequential(self):
        result = process(
            [make_segment(2000, 3000, "B"), make_segment(0, 900, "A"), make_segment(4000, 5000, "C")]
        )
        assert [s.index for s in result.subtitles] == [1, 2, 3]
        # subtitles are sorted chronologically regardless of input order
        assert [s.text for s in result.subtitles] == ["A", "B", "C"]


class TestQualityChecks:
    def test_fast_reading_warning(self):
        text = "x" * 100  # 100 chars in 0.8s = 125 cps
        result = process([make_segment(0, 800, text)])
        assert "FAST_READING" in codes(result.warnings)

    def test_long_line_wrapped_into_lines(self):
        text = " ".join(["word"] * 15)  # 75 chars -> needs 2 lines
        result = process([make_segment(0, 3000, text)])
        sub = result.subtitles[0]
        assert "\n" in sub.text
        assert all(len(line) <= 42 for line in sub.text.split("\n"))
        assert "TOO_MANY_LINES" not in codes(result.warnings)

    def test_original_text_preserved_unwrapped(self):
        text = " ".join(["word"] * 15)
        result = process([make_segment(0, 3000, text)])
        assert result.subtitles[0].original_text == text
        assert result.subtitles[0].is_edited is False

    def test_clean_result_has_no_warnings(self):
        words = (" Hello", " world.")
        result = process([make_segment(1000, 3500, "Hello world.", list(words))])
        assert result.warnings == []
        assert len(result.subtitles) == 1
        assert result.subtitles[0].start_ms == 1000
        assert result.subtitles[0].end_ms == 3500


class TestCustomRules:
    def test_custom_rules_respected(self):
        rules = SubtitleRules(min_duration=2.0, max_chars_per_line=20)
        result = SubtitleProcessor(rules).process([make_segment(0, 900, "Short")])
        assert result.subtitles[0].duration_ms >= 2000
