"""Audio extraction with FFmpeg.

Converts one audio stream of a video into the format required by
Faster-Whisper: WAV / PCM signed 16-bit little-endian / 16 kHz / mono
(section 4.2 of the specification).

Safety properties:
- FFmpeg is invoked with an *argument array* (never a shell string).
- ``-nostdin`` prevents FFmpeg from consuming stdin.
- The process is polled so extraction supports cancellation and timeout.
- The original video file is never modified.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import FFmpegExecutionError, FFmpegNotFoundError, OperationCancelled

logger = logging.getLogger(__name__)

#: bytes per second for mono 16 kHz signed 16-bit audio (16000 * 2).
_BYTES_PER_SECOND = 32000
_WAV_HEADER_BYTES = 44


@dataclass(frozen=True)
class ExtractionResult:
    """Outcome of a successful audio extraction."""

    audio_path: Path
    duration_ms: int | None
    audio_stream_index: int


def _creation_flags() -> int:
    import sys

    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    return 0


class AudioExtractor:
    """Extract audio from video files via FFmpeg."""

    def __init__(self, ffmpeg_path: str = "ffmpeg", timeout_seconds: int = 3600) -> None:
        self.ffmpeg_path = ffmpeg_path
        self.timeout_seconds = timeout_seconds

    def extract(
        self,
        video_path: Path | str,
        output_path: Path | str,
        audio_stream_index: int = 0,
        cancel_event: threading.Event | None = None,
    ) -> ExtractionResult:
        """Extract ``audio_stream_index`` (nth audio stream, 0-based) to WAV.

        Raises:
            FFmpegNotFoundError: FFmpeg is not installed.
            FFmpegExecutionError: FFmpeg failed or timed out.
            OperationCancelled: ``cancel_event`` was set during extraction.
        """
        video_path = Path(video_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if shutil.which(self.ffmpeg_path) is None:
            raise FFmpegNotFoundError(
                "FFmpeg was not found on PATH. Install FFmpeg (see scripts/install_ffmpeg.ps1)."
            )
        if cancel_event is not None and cancel_event.is_set():
            raise OperationCancelled("Audio extraction cancelled before start.")

        args = [
            self.ffmpeg_path,
            "-y",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(video_path),
            "-map",
            f"0:a:{audio_stream_index}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
        logger.info(
            "Extracting audio: stream 0:a:%d from %s", audio_stream_index, video_path.name
        )

        try:
            process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=_creation_flags(),
            )
        except OSError as exc:
            raise FFmpegNotFoundError(f"Could not execute FFmpeg: {exc}") from exc

        stderr_lines: list[str] = []

        def _drain_stderr() -> None:
            assert process.stderr is not None
            for line in process.stderr:
                stderr_lines.append(line.rstrip("\n"))

        reader = threading.Thread(target=_drain_stderr, daemon=True)
        reader.start()

        cancelled = False
        try:
            import time

            deadline = time.monotonic() + self.timeout_seconds
            while True:
                try:
                    returncode = process.wait(timeout=0.25)
                    break
                except subprocess.TimeoutExpired:
                    if cancel_event is not None and cancel_event.is_set():
                        cancelled = True
                        self._terminate(process)
                        raise OperationCancelled("Audio extraction cancelled.") from None
                    if time.monotonic() > deadline:
                        self._terminate(process)
                        raise FFmpegExecutionError(
                            f"FFmpeg timed out after {self.timeout_seconds} seconds."
                        ) from None
        finally:
            reader.join(timeout=2)
            if cancelled:
                _safe_unlink(output_path)

        if returncode != 0:
            _safe_unlink(output_path)
            tail = " | ".join(stderr_lines[-3:]) or "no stderr output"
            raise FFmpegExecutionError(f"FFmpeg failed (exit {returncode}): {tail}")

        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise FFmpegExecutionError("FFmpeg finished but produced no audio output.")

        duration_ms = int(
            round((output_path.stat().st_size - _WAV_HEADER_BYTES)
                  / _BYTES_PER_SECOND * 1000)
        )
        logger.info("Audio extracted to %s (~%d ms)", output_path, duration_ms)
        return ExtractionResult(
            audio_path=output_path,
            duration_ms=max(duration_ms, 0),
            audio_stream_index=audio_stream_index,
        )

    @staticmethod
    def _terminate(process: subprocess.Popen[str]) -> None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover
                logger.error("FFmpeg process could not be terminated.")


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:  # pragma: no cover - best effort cleanup
        logger.warning("Could not remove partial output %s", path)
