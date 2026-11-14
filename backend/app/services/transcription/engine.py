"""Transcription engine abstraction (section 5 of the specification).

The rest of the system depends only on :class:`TranscriptionEngine`, never on
Faster-Whisper directly, so the AI backend can be swapped without touching
the pipeline, worker or API layers.

All timestamps are integer milliseconds.  Text is always in the *original*
spoken language - the engine never translates.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event

#: Called with ``(fraction 0..1, human-readable stage message)``.
ProgressCallback = Callable[[float, str], None]

_WHITESPACE_RE = re.compile(r"[ \t ]+")


def normalize_text(text: str) -> str:
    """Collapse runs of spaces/tabs to single spaces and strip the ends.

    Newlines are removed (Whisper never emits meaningful ones) and Thai
    phrase spacing is preserved as-is.
    """
    return _WHITESPACE_RE.sub(" ", text.replace("\n", " ")).strip()


@dataclass(frozen=True)
class WordTiming:
    """A single detected word with its timing."""

    start_ms: int
    end_ms: int
    word: str
    probability: float | None = None


@dataclass(frozen=True)
class TranscribedSegment:
    """A raw transcription segment exactly as produced by the model."""

    start_ms: int
    end_ms: int
    text: str
    words: tuple[WordTiming, ...] = ()
    confidence: float | None = None
    raw: dict = field(default_factory=dict)

    def reconstruct_from_words(self) -> str | None:
        """Text rebuilt by concatenating raw word tokens (preserves spacing),
        or ``None`` when word timings are unavailable."""
        if not self.words:
            return None
        joined = "".join(w.word for w in self.words)
        return normalize_text(joined)


@dataclass(frozen=True)
class TranscriptionResult:
    """Complete raw transcription output for one audio file."""

    language: str | None
    language_probability: float | None
    duration_ms: int | None
    segments: tuple[TranscribedSegment, ...]

    def to_payload(self) -> dict:
        """Serializable raw transcript payload (stored as transcript.json)."""
        return {
            "language": self.language,
            "language_probability": self.language_probability,
            "duration_ms": self.duration_ms,
            "segments": [
                {
                    "start_ms": s.start_ms,
                    "end_ms": s.end_ms,
                    "text": s.text,
                    "confidence": s.confidence,
                    "words": [
                        {
                            "start_ms": w.start_ms,
                            "end_ms": w.end_ms,
                            "word": w.word,
                            "probability": w.probability,
                        }
                        for w in s.words
                    ],
                }
                for s in self.segments
            ],
        }


@dataclass
class TranscriptionOptions:
    """User-facing transcription settings (section 3.4)."""

    model: str = "large-v3"
    language: str | None = None  # None = auto-detect
    task: str = "transcribe"  # never "translate" in this application
    beam_size: int = 5
    best_of: int = 5
    temperature: float = 0.0
    vad_filter: bool = True
    word_timestamps: bool = True
    # Anti-drift defaults for long videos: feeding the previous window's text
    # back as context makes one bad decode (typically right after a long
    # silent stretch) poison every following window.  Disabled by default;
    # ``condition_on_previous_text=True`` is only worth it on short, clean
    # audio.  ``hallucination_silence_threshold`` (needs word_timestamps)
    # tells faster-whisper to skip silent periods when a hallucination is
    # suspected instead of decoding noise into text.
    condition_on_previous_text: bool = False
    hallucination_silence_threshold: float | None = 2.0
    initial_prompt: str | None = None
    # Optional Silero VAD tuning (section 19 "Optimize VAD"); None = engine default
    vad_threshold: float | None = None
    vad_min_silence_ms: int | None = None
    # Pipeline flag (NOT an engine kwarg): run pyannote speaker diarization
    # after transcription and label the subtitle rows (post-spec feature).
    diarize: bool = False

    def to_engine_kwargs(self) -> dict:
        """Keyword arguments passed to the concrete engine's transcribe().

        ``None`` values are dropped so auto-detect settings use engine
        defaults instead of overriding them.
        """
        return {
            "language": self.language,
            "task": self.task,
            "beam_size": self.beam_size,
            "best_of": self.best_of,
            "temperature": self.temperature,
            "vad_filter": self.vad_filter,
            "word_timestamps": self.word_timestamps,
            "condition_on_previous_text": self.condition_on_previous_text,
            "hallucination_silence_threshold": self.hallucination_silence_threshold,
            "initial_prompt": self.initial_prompt,
        }


class TranscriptionEngine(ABC):
    """Abstract speech-to-text engine."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Name of the model currently configured for this engine."""

    @abstractmethod
    def load_model(self) -> None:
        """Load the model into memory (may take significant time/VRAM)."""

    @abstractmethod
    def is_loaded(self) -> bool:
        """True when a model is loaded and ready."""

    @abstractmethod
    def transcribe(
        self,
        audio_path: Path | str,
        options: TranscriptionOptions,
        progress_callback: ProgressCallback | None = None,
        cancel_event: Event | None = None,
    ) -> TranscriptionResult:
        """Transcribe an audio file and return raw segments.

        The implementation must fully consume the underlying segment
        generator before returning (section 5 of the specification).
        """

    @abstractmethod
    def unload_model(self) -> None:
        """Release the model and free GPU/CPU memory."""


def make_segments_from_payload(payload: Sequence[dict]) -> tuple[TranscribedSegment, ...]:
    """Rebuild segments from a transcript.json payload (used by reprocess)."""
    segments: list[TranscribedSegment] = []
    for item in payload:
        words = tuple(
            WordTiming(
                start_ms=int(w["start_ms"]),
                end_ms=int(w["end_ms"]),
                word=w.get("word", ""),
                probability=w.get("probability"),
            )
            for w in item.get("words", [])
        )
        segments.append(
            TranscribedSegment(
                start_ms=int(item["start_ms"]),
                end_ms=int(item["end_ms"]),
                text=item.get("text", ""),
                words=words,
                confidence=item.get("confidence"),
            )
        )
    return tuple(segments)
