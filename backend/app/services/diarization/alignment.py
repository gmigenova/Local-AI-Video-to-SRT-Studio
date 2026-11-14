"""Assign diarization speaker turns to subtitle rows (pure functions).

Each subtitle gets the speaker whose turns overlap it the most (total
overlap in milliseconds).  A row with no overlap at all keeps no speaker -
typing silence or cross-talk noise is better left unlabelled than guessed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.services.diarization.service import DiarizationTurn
from app.services.subtitle.models import Subtitle


@dataclass
class SpeakerAssignment:
    """Speaker label per row, aligned by index with the input list."""

    speakers: list[str | None] = field(default_factory=list)

    def apply_to(self, subtitles: Sequence[Subtitle]) -> int:
        """Set ``speaker`` on the rows in place; returns labelled count."""
        labelled = 0
        for sub, speaker in zip(subtitles, self.speakers, strict=False):
            sub.speaker = speaker
            if speaker:
                labelled += 1
        return labelled


def _overlap_ms(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def assign_speakers_to_subtitles(
    subtitles: Sequence[Subtitle], turns: Sequence[DiarizationTurn]
) -> SpeakerAssignment:
    """Majority-overlap assignment: for each row, sum the overlap duration
    per speaker across all turns and pick the argmax (None when zero)."""
    speakers: list[str | None] = []
    for sub in subtitles:
        totals: dict[str, int] = {}
        for turn in turns:
            overlap = _overlap_ms(sub.start_ms, sub.end_ms, turn.start_ms, turn.end_ms)
            if overlap > 0:
                totals[turn.speaker] = totals.get(turn.speaker, 0) + overlap
        if totals:
            speakers.append(max(totals, key=lambda name: totals[name]))
        else:
            speakers.append(None)
    return SpeakerAssignment(speakers=speakers)
