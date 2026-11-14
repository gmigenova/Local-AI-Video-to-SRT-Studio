"""Application error types.

All application-specific exceptions derive from :class:`VideoToSrtError` so
callers (CLI now, REST API later) can present a clean message instead of a
stack trace, while the full details are written to logs.
"""

from __future__ import annotations


class VideoToSrtError(Exception):
    """Base class for all application errors."""


class MediaValidationError(VideoToSrtError):
    """The media file is unsupported, unreadable or has no audio stream."""


class UnsupportedFileTypeError(MediaValidationError):
    """The file extension is not in the supported list."""


class NoAudioStreamError(MediaValidationError):
    """The media file does not contain an audio stream."""


class FFmpegNotFoundError(VideoToSrtError):
    """FFmpeg / FFprobe executable is not installed or not on PATH."""


class FFmpegExecutionError(VideoToSrtError):
    """An FFmpeg/FFprobe process failed, timed out or produced no output."""


class ModelLoadError(VideoToSrtError):
    """An AI model could not be loaded (missing files, OOM, bad config)."""


class TranscriptionError(VideoToSrtError):
    """Transcription failed."""


class OperationCancelled(VideoToSrtError):
    """The operation was cancelled by the user."""


class ExportError(VideoToSrtError):
    """Subtitle export failed."""


class TranslationError(VideoToSrtError):
    """Subtitle translation failed (bad config, API error, network)."""


class DiarizationError(VideoToSrtError):
    """Speaker diarization failed after it was properly enabled."""


class DiarizationUnavailable(VideoToSrtError):
    """Speaker diarization is requested but not configured (missing token
    or the optional pyannote dependency)."""
