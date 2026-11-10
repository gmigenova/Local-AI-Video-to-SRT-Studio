"""Media inspection using FFprobe.

Runs FFprobe as a subprocess with an argument array (never a shell string)
and parses its JSON output into typed dataclasses.  This is the authoritative
content validation described in section 4.1 of the specification: a file is
only accepted if FFprobe can read it and it contains at least one audio
stream.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.config import SUPPORTED_VIDEO_EXTENSIONS
from app.core.errors import (
    FFmpegExecutionError,
    FFmpegNotFoundError,
    MediaValidationError,
    NoAudioStreamError,
    UnsupportedFileTypeError,
)

logger = logging.getLogger(__name__)

_PROBE_TIMEOUT_SECONDS = 60


def is_supported_video_file(path: Path) -> bool:
    """True when the file extension is one of the supported containers."""
    return path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS


@dataclass(frozen=True)
class AudioStreamInfo:
    """A single audio stream inside a media container."""

    stream_index: int  # absolute stream index as used by ``-map 0:a:N``
    codec_name: str
    channels: int | None
    sample_rate: int | None
    language: str | None

    @property
    def label(self) -> str:
        lang = self.language or "unknown"
        return f"#{self.stream_index} {self.codec_name} {self.channels or '?'}ch {lang}"


@dataclass(frozen=True)
class MediaInfo:
    """Metadata for an uploaded media file."""

    file_path: Path
    file_size_bytes: int
    duration_ms: int | None
    container: str | None
    video_codec: str | None
    width: int | None
    height: int | None
    audio_streams: tuple[AudioStreamInfo, ...]

    @property
    def has_audio(self) -> bool:
        return len(self.audio_streams) > 0

    def default_audio_stream(self) -> AudioStreamInfo | None:
        """First audio stream (prefers one with a language tag)."""
        if not self.audio_streams:
            return None
        tagged = [s for s in self.audio_streams if s.language]
        return (tagged or list(self.audio_streams))[0]

    def audio_stream_by_index(self, absolute_index: int) -> AudioStreamInfo | None:
        for stream in self.audio_streams:
            if stream.stream_index == absolute_index:
                return stream
        return None


def _creation_flags() -> int:
    import sys

    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    return 0


def probe_video(path: Path | str, ffprobe_path: str = "ffprobe") -> MediaInfo:
    """Inspect a media file with FFprobe and return typed metadata.

    Raises:
        UnsupportedFileTypeError: the extension is not in the allowlist.
        FFmpegNotFoundError: FFprobe is not installed.
        NoAudioStreamError: the file has no audio stream.
        MediaValidationError: the file is missing, unreadable or corrupt.
    """
    path = Path(path)
    if not path.is_file():
        raise MediaValidationError(f"File not found: {path.name}")
    if path.stat().st_size == 0:
        raise MediaValidationError(f"File is empty: {path.name}")
    if not is_supported_video_file(path):
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{path.suffix}'. Supported: "
            + ", ".join(sorted(SUPPORTED_VIDEO_EXTENSIONS))
        )
    if shutil.which(ffprobe_path) is None:
        raise FFmpegNotFoundError(
            "FFprobe was not found on PATH. Install FFmpeg (see scripts/install_ffmpeg.ps1)."
        )

    args = [
        ffprobe_path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            args,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            encoding="utf-8",
            errors="replace",
            creationflags=_creation_flags(),
        )
    except subprocess.TimeoutExpired as exc:
        raise FFmpegExecutionError("FFprobe timed out while reading the file.") from exc
    except OSError as exc:
        raise FFmpegNotFoundError(f"Could not execute FFprobe: {exc}") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        snippet = detail[-1] if detail else "unknown error"
        logger.warning("FFprobe failed for %s: %s", path.name, snippet)
        raise MediaValidationError(
            f"The file could not be read as a media container ({snippet})."
        )

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise MediaValidationError("FFprobe returned unreadable output.") from exc

    fmt = payload.get("format") or {}
    duration_ms: int | None = None
    if fmt.get("duration") not in (None, ""):
        try:
            duration_ms = int(round(float(fmt["duration"]) * 1000))
        except ValueError:
            duration_ms = None

    video_codec: str | None = None
    width: int | None = None
    height: int | None = None
    audio_streams: list[AudioStreamInfo] = []

    for stream in payload.get("streams", []):
        codec_type = stream.get("codec_type")
        if codec_type == "video" and video_codec is None:
            video_codec = stream.get("codec_name")
            width = stream.get("width")
            height = stream.get("height")
        elif codec_type == "audio":
            sample_rate = stream.get("sample_rate")
            audio_streams.append(
                AudioStreamInfo(
                    stream_index=int(stream.get("index", 0)),
                    codec_name=stream.get("codec_name", "unknown"),
                    channels=stream.get("channels"),
                    sample_rate=int(sample_rate) if sample_rate else None,
                    language=(stream.get("tags") or {}).get("language"),
                )
            )

    if not audio_streams:
        raise NoAudioStreamError("The file does not contain an audio stream.")

    info = MediaInfo(
        file_path=path,
        file_size_bytes=path.stat().st_size,
        duration_ms=duration_ms,
        container=fmt.get("format_name"),
        video_codec=video_codec,
        width=width,
        height=height,
        audio_streams=tuple(audio_streams),
    )
    logger.info(
        "Probed %s: duration=%s ms, video=%s, audio streams=%d",
        path.name,
        info.duration_ms,
        info.video_codec,
        len(info.audio_streams),
    )
    return info
