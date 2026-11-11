"""Subtitle burn-in (hardsub) with FFmpeg.

Re-encodes the original video with the job's current subtitles rendered
permanently into the picture (libass ``subtitles`` filter).

Safety properties (same invariants as the audio extractor, §17):
- FFmpeg is invoked with an *argument array* (never a shell string).
- ``-nostdin`` prevents FFmpeg from consuming stdin.
- The process is polled, so a render supports cancellation and timeout.
- The original video file is never modified; output goes to
  ``storage/renders/{render_id}/output.mp4``.

Windows note: the ``subtitles`` filter argument is parsed by FFmpeg's own
filtergraph parser, where ``:`` is a separator - an absolute path such as
``C:\\...\\render.srt`` would need heavy escaping. Instead the process runs
with ``cwd`` set to the directory holding the SRT and the filter references
the bare file name, which we control (``render.srt``).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import FFmpegExecutionError, FFmpegNotFoundError, OperationCancelled

logger = logging.getLogger(__name__)

#: audio codecs that can be stream-copied into MP4 without re-encoding.
#: Anything else (opus, vorbis, pcm_*, ...) is transcoded to AAC.
MP4_AUDIO_CODECS: frozenset[str] = frozenset({"aac", "mp3", "ac3", "eac3", "alac"})

#: name of the SRT written next to the output; referenced bare by the
#: filter (see module docstring) so it must stay filter-safe.
RENDER_SRT_NAME = "render.srt"

DEFAULT_CRF = 21
DEFAULT_PRESET = "veryfast"


@dataclass(frozen=True)
class BurnResult:
    """Outcome of a successful burn-in render."""

    output_path: Path
    file_size: int


def sanitize_font_name(font_name: str) -> str:
    """Strip characters that would break the force_style filter value."""
    cleaned = font_name.replace("'", "").replace("\\", "").replace(":", "").strip()
    return cleaned


def build_burn_args(
    video_path: Path | str,
    srt_path: Path | str,
    output_path: Path | str,
    *,
    font_name: str | None = None,
    crf: int = DEFAULT_CRF,
    preset: str = DEFAULT_PRESET,
    audio_codec: str | None = None,
) -> list[str]:
    """Build the FFmpeg argument array for a hardsub render.

    The SRT is referenced by file name only - the caller must run FFmpeg
    with ``cwd`` set to ``srt_path.parent`` (see :class:`SubtitleBurner`).
    """
    srt_path = Path(srt_path)
    if srt_path.name != RENDER_SRT_NAME:
        raise ValueError(
            f"The burn filter only supports the fixed name '{RENDER_SRT_NAME}'."
        )

    filter_value = f"subtitles={srt_path.name}"
    if font_name:
        # single quotes protect the space + '=' inside the filtergraph value
        filter_value += f":force_style='FontName={sanitize_font_name(font_name)}'"

    copy_audio = audio_codec is not None and audio_codec.lower() in MP4_AUDIO_CODECS
    audio_args = ["-c:a", "copy"] if copy_audio else ["-c:a", "aac", "-b:a", "192k"]

    return [
        "ffmpeg",
        "-y",
        "-nostdin",
        "-hide_banner",
        "-v",
        "error",
        "-progress",
        "pipe:1",
        "-i",
        str(video_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",  # optional: videos without audio still render
        "-vf",
        filter_value,
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        *audio_args,
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def _creation_flags() -> int:
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    return 0


class SubtitleBurner:
    """Burn an SRT into a video via FFmpeg (libass)."""

    def __init__(self, ffmpeg_path: str = "ffmpeg", timeout_seconds: int = 14400) -> None:
        self.ffmpeg_path = ffmpeg_path
        self.timeout_seconds = timeout_seconds

    def burn(
        self,
        video_path: Path | str,
        srt_path: Path | str,
        output_path: Path | str,
        *,
        duration_ms: int | None = None,
        font_name: str | None = None,
        audio_codec: str | None = None,
        cancel_event: threading.Event | None = None,
        on_progress: Callable[[float], None] | None = None,
    ) -> BurnResult:
        """Render ``srt_path`` over ``video_path`` into ``output_path``.

        ``on_progress`` receives a 0..1 fraction derived from FFmpeg's
        reported output time vs. ``duration_ms`` - it is only called when
        both are known (honest progress, §11.4; no fabricated numbers).

        Raises:
            FFmpegNotFoundError: FFmpeg is not installed.
            FFmpegExecutionError: FFmpeg failed or timed out.
            OperationCancelled: ``cancel_event`` was set during the render.
        """
        video_path = Path(video_path)
        srt_path = Path(srt_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if shutil.which(self.ffmpeg_path) is None:
            raise FFmpegNotFoundError(
                "FFmpeg was not found on PATH. Install FFmpeg (see scripts/install_ffmpeg.ps1)."
            )
        if cancel_event is not None and cancel_event.is_set():
            raise OperationCancelled("Render cancelled before start.")

        args = build_burn_args(
            video_path,
            srt_path,
            output_path,
            font_name=font_name,
            audio_codec=audio_codec,
        )
        logger.info(
            "Burning subtitles: %s + %s -> %s",
            video_path.name, srt_path.name, output_path.name,
        )

        try:
            process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
                args,
                cwd=str(srt_path.parent),  # filter uses the bare SRT name
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=_creation_flags(),
            )
        except OSError as exc:
            raise FFmpegNotFoundError(f"Could not execute FFmpeg: {exc}") from exc

        # FFmpeg -progress writes key=value lines to stdout
        out_time_us = [-1]
        stderr_lines: list[str] = []
        pipes = (process.stdout, process.stderr)

        def _drain(pipe, sink: list[str], progress: bool) -> None:  # noqa: ANN001
            for line in pipe:
                stripped = line.strip()
                if progress:
                    key, _, value = stripped.partition("=")
                    if key == "out_time_us" and value.lstrip("-").isdigit():
                        out_time_us[0] = int(value)
                else:
                    sink.append(stripped)

        readers = [
            threading.Thread(target=_drain, args=(pipes[0], [], True), daemon=True),
            threading.Thread(target=_drain, args=(pipes[1], stderr_lines, False), daemon=True),
        ]
        for reader in readers:
            reader.start()

        cancelled = False
        try:
            import time

            deadline = time.monotonic() + self.timeout_seconds
            last_reported = -1.0
            while True:
                try:
                    returncode = process.wait(timeout=0.25)
                    break
                except subprocess.TimeoutExpired:
                    if cancel_event is not None and cancel_event.is_set():
                        cancelled = True
                        self._terminate(process)
                        raise OperationCancelled("Render cancelled.") from None
                    if time.monotonic() > deadline:
                        self._terminate(process)
                        raise FFmpegExecutionError(
                            f"FFmpeg timed out after {self.timeout_seconds} seconds."
                        ) from None
                    if (
                        on_progress is not None
                        and duration_ms
                        and duration_ms > 0
                        and out_time_us[0] >= 0
                    ):
                        fraction = min(out_time_us[0] / 1000.0 / duration_ms, 1.0)
                        # throttle: report at most every 1% change
                        if fraction - last_reported >= 0.01:
                            last_reported = fraction
                            on_progress(fraction)
        finally:
            for reader in readers:
                reader.join(timeout=2)
            if cancelled:
                _safe_unlink(output_path)

        if returncode != 0:
            _safe_unlink(output_path)
            tail = " | ".join(stderr_lines[-3:]) or "no stderr output"
            raise FFmpegExecutionError(f"FFmpeg failed (exit {returncode}): {tail}")

        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise FFmpegExecutionError("FFmpeg finished but produced no video output.")

        file_size = output_path.stat().st_size
        logger.info("Burn-in render finished: %s (%d bytes)", output_path, file_size)
        return BurnResult(output_path=output_path, file_size=file_size)

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
