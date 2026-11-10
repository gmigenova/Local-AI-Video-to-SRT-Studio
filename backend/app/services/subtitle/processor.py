"""Subtitle processing engine (section 6 of the specification).

Raw Whisper segments are *not* used as subtitles directly.  This module runs
the staged pipeline:

1. Normalize text, drop empty segments.
2. Validate / repair timestamps.
3. Split over-long segments (word-timing aware, sentence-boundary aware).
4. Merge tiny adjacent fragments (never across sentence boundaries).
5. Enforce minimum display duration and the gap / no-overlap rule.
6. Wrap text into at most ``max_lines`` lines (Thai-aware).
7. Assign sequential indices and run quality checks.

Design constraints from the specification:
- Timestamps are never stretched excessively to satisfy reading speed; the
  reading speed rule only produces warnings.
- Timing is never fabricated for words without word timestamps: a long
  segment without word timings stays intact and is reported as a warning.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace

from pydantic import BaseModel

from app.services.subtitle.models import Subtitle, SubtitleWarning
from app.services.subtitle.text_splitting import wrap_text
from app.services.transcription.engine import TranscribedSegment, WordTiming, normalize_text

logger = logging.getLogger(__name__)

SENTENCE_ENDINGS = (".", "!", "?", "。", "！", "？", "…")

#: Width applied to a segment whose end <= start so it stays renderable.
_MIN_SLICE_MS = 200


class SubtitleRules(BaseModel):
    """Configurable subtitle rules (section 6.1). Defaults, not absolutes."""

    max_lines: int = 2
    max_chars_per_line: int = 42
    min_duration: float = 0.8
    max_duration: float = 7.0
    max_reading_speed: float = 20.0  # characters per second
    gap_between_subtitles: float = 0.05
    preserve_sentence_boundaries: bool = True
    merge_max_gap: float = 0.3  # adjacent items with a smaller gap may merge

    @property
    def min_duration_ms(self) -> int:
        return int(self.min_duration * 1000)

    @property
    def max_duration_ms(self) -> int:
        return int(self.max_duration * 1000)

    @property
    def gap_ms(self) -> int:
        return int(self.gap_between_subtitles * 1000)

    @property
    def merge_max_gap_ms(self) -> int:
        return int(self.merge_max_gap * 1000)

    @property
    def max_chars_total(self) -> int:
        return self.max_lines * self.max_chars_per_line


@dataclass
class SubtitleProcessingResult:
    subtitles: list[Subtitle]
    warnings: list[SubtitleWarning]


@dataclass
class _Item:
    """Internal working item before index assignment / wrapping."""

    start_ms: int
    end_ms: int
    text: str
    words: tuple[WordTiming, ...] = ()

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


def _ends_sentence(token: str) -> bool:
    stripped = token.rstrip()
    return bool(stripped) and stripped[-1] in SENTENCE_ENDINGS


def _join_text(left: str, right: str) -> str:
    if left.endswith(" ") or right.startswith(" "):
        return normalize_text(left + right)
    return normalize_text(left + " " + right)


def _words_text(words: Sequence[WordTiming]) -> str:
    return normalize_text("".join(w.word for w in words))


class SubtitleProcessor:
    """Converts raw transcription segments into subtitle entries."""

    def __init__(self, rules: SubtitleRules | None = None) -> None:
        self.rules = rules or SubtitleRules()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def process(self, segments: Sequence[TranscribedSegment]) -> SubtitleProcessingResult:
        items = self._build_items(segments)
        items = self._fix_timestamps(items)
        items.sort(key=lambda i: (i.start_ms, i.end_ms))
        items = self._split_long_items(items)
        items = self._merge_items(items)
        items = self._enforce_timing(items)
        subtitles = self._finalize(items)
        warnings = self.quality_check(subtitles)
        if warnings:
            logger.info("Subtitle quality checks: %d warning(s).", len(warnings))
        return SubtitleProcessingResult(subtitles=subtitles, warnings=warnings)

    # ------------------------------------------------------------------
    # Stages
    # ------------------------------------------------------------------
    def _build_items(self, segments: Sequence[TranscribedSegment]) -> list[_Item]:
        items: list[_Item] = []
        for segment in segments:
            text = normalize_text(segment.text)
            if not text:
                continue  # remove empty segments
            items.append(
                _Item(
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    text=text,
                    words=segment.words,
                )
            )
        return items

    def _fix_timestamps(self, items: list[_Item]) -> list[_Item]:
        fixed: list[_Item] = []
        for item in items:
            start = max(item.start_ms, 0)
            end = item.end_ms
            if end <= start:
                logger.debug("Repairing invalid timestamps in segment '%s...'", item.text[:20])
                end = start + _MIN_SLICE_MS
            fixed.append(replace(item, start_ms=start, end_ms=end))
        return fixed

    def _split_long_items(self, items: list[_Item]) -> list[_Item]:
        out: list[_Item] = []
        for item in items:
            needs_split = (
                item.duration_ms > self.rules.max_duration_ms
                or len(wrap_text(item.text, self.rules.max_chars_per_line, self.rules.max_lines)
                        .splitlines()) > self.rules.max_lines
            )
            if needs_split and item.words:
                out.extend(self._split_item(item))
            else:
                out.append(item)
        return out

    def _wrapped_lines(self, text: str) -> int:
        """How many display lines ``text`` needs under the wrapping rules."""
        return (
            wrap_text(text, self.rules.max_chars_per_line, self.rules.max_lines).count("\n")
            + 1
        )

    def _split_item(self, item: _Item) -> list[_Item]:
        """Split one item into chunks using word timings.

        Chunks obey ``max_duration`` and wrap into at most ``max_lines``
        lines (with ``max_chars_total`` as a hard safety cap); break points
        prefer sentence endings when ``preserve_sentence_boundaries`` is set.
        """
        rules = self.rules
        max_chars = rules.max_chars_total
        max_dur = rules.max_duration_ms

        chunks: list[list[WordTiming]] = []
        current: list[WordTiming] = []

        for word in item.words:
            if current:
                candidate = current + [word]
                candidate_text = _words_text(candidate)
                too_big = (
                    self._wrapped_lines(candidate_text) > rules.max_lines
                    or len(candidate_text) > max_chars
                )
                too_long = (word.end_ms - current[0].start_ms) > max_dur
                if too_big or too_long:
                    split_at = self._preferred_split_index(current, max_chars)
                    if split_at is not None:
                        chunks.append(current[:split_at])
                        current = current[split_at:]
                    else:
                        chunks.append(current)
                        current = []
                    remainder_text = _words_text(current + [word])
                    if (
                        self._wrapped_lines(remainder_text) > rules.max_lines
                        or len(remainder_text) > max_chars
                    ):
                        # remainder already too big even before adding: flush it too
                        if current:
                            chunks.append(current)
                            current = []
            current.append(word)

        if current:
            chunks.append(current)

        pieces: list[_Item] = []
        for chunk_words in chunks:
            text = _words_text(chunk_words)
            if not text:
                continue
            # chunk timing comes from its own words - never from the parent
            # segment start, or later chunks would inherit an early start.
            start = chunk_words[0].start_ms
            end = max(chunk_words[-1].end_ms, start + 1)
            pieces.append(_Item(start_ms=start, end_ms=end, text=text, words=tuple(chunk_words)))
        if len(pieces) <= 1 and pieces:
            # Nothing gained; keep the original item (timing may be more accurate).
            return [replace(item, words=item.words)]
        logger.debug("Split one segment into %d subtitle chunks.", len(pieces))
        return pieces

    def _preferred_split_index(
        self, words: list[WordTiming], max_chars: int
    ) -> int | None:
        """Last sentence-ending position that keeps a reasonable chunk size."""
        if not self.rules.preserve_sentence_boundaries:
            return None
        min_chars = int(max_chars * 0.25)
        for idx in range(len(words) - 1, 0, -1):
            if _ends_sentence(words[idx - 1].word):
                if len(_words_text(words[:idx])) >= min_chars:
                    return idx
        return None

    def _merge_items(self, items: list[_Item]) -> list[_Item]:
        """Merge adjacent fragments separated by a very small gap.

        Never merges across sentence boundaries (when enabled) and never
        produces items exceeding ``max_duration`` or ``max_chars_total``.
        """
        merged: list[_Item] = []
        for item in items:
            if merged:
                prev = merged[-1]
                gap = item.start_ms - prev.end_ms
                sentence_break = (
                    self.rules.preserve_sentence_boundaries
                    and _ends_sentence(prev.text)
                )
                combined_text = _join_text(prev.text, item.text)
                fits = (
                    item.end_ms - prev.start_ms <= self.rules.max_duration_ms
                    and self._wrapped_lines(combined_text) <= self.rules.max_lines
                    and len(combined_text) <= self.rules.max_chars_total
                )
                if gap <= self.rules.merge_max_gap_ms and not sentence_break and fits:
                    prev.end_ms = max(prev.end_ms, item.end_ms)
                    prev.text = combined_text
                    prev.words = prev.words + item.words
                    continue
            merged.append(replace(item))
        return merged

    def _enforce_timing(self, items: list[_Item]) -> list[_Item]:
        """Apply the gap / no-overlap rule, then minimum duration.

        Order matters: starts are normalized first, then durations are
        extended - so the min-duration math always sees final start times.
        Durations are extended only up to the next subtitle's start minus
        the configured gap; timestamps are never stretched aggressively.
        """
        rules = self.rules

        # 1. gap / no-overlap normalization
        for i in range(1, len(items)):
            prev, cur = items[i - 1], items[i]
            min_start = prev.end_ms + rules.gap_ms
            if cur.start_ms < min_start:
                cur.start_ms = min_start
                if cur.end_ms <= cur.start_ms:
                    cur.end_ms = cur.start_ms + 1

        # 2. minimum display duration
        for i, item in enumerate(items):
            if item.duration_ms < rules.min_duration_ms:
                desired_end = item.start_ms + rules.min_duration_ms
                next_start = items[i + 1].start_ms if i + 1 < len(items) else None
                limit = next_start - rules.gap_ms if next_start is not None else None
                if limit is None or limit >= desired_end:
                    item.end_ms = max(item.end_ms, desired_end)
                elif limit > item.end_ms:
                    item.end_ms = limit
                # else: cannot extend without creating an overlap; leave as-is.
        return items

    def _finalize(self, items: list[_Item]) -> list[Subtitle]:
        subtitles: list[Subtitle] = []
        for i, item in enumerate(items, start=1):
            wrapped = wrap_text(
                item.text, self.rules.max_chars_per_line, self.rules.max_lines
            )
            subtitles.append(
                Subtitle(
                    index=i,
                    start_ms=item.start_ms,
                    end_ms=item.end_ms,
                    text=wrapped,
                    original_text=item.text,
                )
            )
        return subtitles

    # ------------------------------------------------------------------
    # Quality checks (section 11.6)
    # ------------------------------------------------------------------
    def quality_check(self, subtitles: Sequence[Subtitle]) -> list[SubtitleWarning]:
        rules = self.rules
        warnings: list[SubtitleWarning] = []
        prev: Subtitle | None = None

        for sub in subtitles:
            flat_text = sub.text.replace("\n", " ")
            duration_s = max(sub.duration_ms, 0) / 1000.0

            if not flat_text.strip():
                warnings.append(
                    SubtitleWarning(sub.index, "EMPTY_TEXT", "Subtitle text is empty.")
                )
            if sub.start_ms < 0 or sub.end_ms <= sub.start_ms:
                warnings.append(
                    SubtitleWarning(
                        sub.index,
                        "INVALID_TIMESTAMP",
                        f"Invalid timestamps ({sub.start_ms} -> {sub.end_ms} ms).",
                    )
                )
            if prev is not None and sub.start_ms < prev.end_ms + rules.gap_ms:
                warnings.append(
                    SubtitleWarning(
                        sub.index,
                        "OVERLAP",
                        f"Starts before previous subtitle #{prev.index} ends "
                        f"(gap rule {rules.gap_between_subtitles}s).",
                    )
                )
            if sub.duration_ms < rules.min_duration_ms:
                warnings.append(
                    SubtitleWarning(
                        sub.index,
                        "TOO_SHORT",
                        f"Display duration {sub.duration_ms} ms is below the "
                        f"{rules.min_duration}s minimum.",
                    )
                )
            if sub.duration_ms > rules.max_duration_ms:
                warnings.append(
                    SubtitleWarning(
                        sub.index,
                        "TOO_LONG_DURATION",
                        f"Display duration exceeds the {rules.max_duration}s maximum.",
                    )
                )
            for line in sub.text.split("\n"):
                if len(line) > rules.max_chars_per_line:
                    warnings.append(
                        SubtitleWarning(
                            sub.index,
                            "LINE_TOO_LONG",
                            f"Line has {len(line)} characters "
                            f"(limit {rules.max_chars_per_line}).",
                        )
                    )
                    break
            if sub.text.count("\n") + 1 > rules.max_lines:
                warnings.append(
                    SubtitleWarning(
                        sub.index,
                        "TOO_MANY_LINES",
                        f"Text needs {sub.text.count(chr(10)) + 1} lines "
                        f"(limit {rules.max_lines}).",
                    )
                )
            if duration_s > 0 and len(flat_text) / duration_s > rules.max_reading_speed:
                warnings.append(
                    SubtitleWarning(
                        sub.index,
                        "FAST_READING",
                        f"Reading speed {len(flat_text) / duration_s:.0f} chars/s "
                        f"exceeds {rules.max_reading_speed:.0f}.",
                    )
                )
            prev = sub

        for expected, sub in enumerate(subtitles, start=1):
            if sub.index != expected:
                warnings.append(
                    SubtitleWarning(sub.index, "MISSING_INDEX", "Subtitle indices are not sequential.")
                )
                break
        return warnings
