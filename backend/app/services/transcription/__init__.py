"""Transcription engine abstraction and Faster-Whisper implementation."""

from app.services.transcription.engine import (
    ProgressCallback,
    TranscribedSegment,
    TranscriptionEngine,
    TranscriptionOptions,
    TranscriptionResult,
    WordTiming,
)
from app.services.transcription.faster_whisper_engine import FasterWhisperEngine
from app.services.transcription.model_manager import ModelManager

__all__ = [
    "FasterWhisperEngine",
    "ModelManager",
    "ProgressCallback",
    "TranscribedSegment",
    "TranscriptionEngine",
    "TranscriptionOptions",
    "TranscriptionResult",
    "WordTiming",
]
