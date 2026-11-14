"""Speaker diarization (pyannote.audio, local-only, post-spec feature).

Overrides the v1 spec non-goal (writing-block.md §1.1 / §20 "do not
implement speaker diarization") by explicit owner decision - everything
still runs locally; the HuggingFace token is only used to download the
model weights.
"""

from app.services.diarization.alignment import (
    SpeakerAssignment,
    assign_speakers_to_subtitles,
)
from app.services.diarization.service import (
    DiarizationService,
    DiarizationTurn,
    make_diarizer,
    read_diarization_payload,
    write_diarization_payload,
)

__all__ = [
    "DiarizationService",
    "DiarizationTurn",
    "SpeakerAssignment",
    "assign_speakers_to_subtitles",
    "make_diarizer",
    "read_diarization_payload",
    "write_diarization_payload",
]
