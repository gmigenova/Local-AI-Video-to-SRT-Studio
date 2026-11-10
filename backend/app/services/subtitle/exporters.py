"""Subtitle exporters: SRT, VTT, TXT, JSON (section 12).

- Timestamps are converted to strings only here, never before.
- SRT uses CRLF line endings and UTF-8 (optionally with BOM) for Windows
  compatibility; VTT/TXT/JSON use LF.
- Numbering is always re-sequenced so exported files are valid even if the
  editor leaves gaps.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path

from app.core.errors import ExportError
from app.services.subtitle.models import Subtitle

logger = logging.getLogger(__name__)


def format_timestamp_srt(ms: int) -> str:
    """Format milliseconds as an SRT timestamp: HH:MM:SS,mmm."""
    if ms < 0:
        ms = 0
    hours = ms // 3_600_000
    minutes = (ms % 3_600_000) // 60_000
    seconds = (ms % 60_000) // 1000
    milliseconds = ms % 1000
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def format_timestamp_vtt(ms: int) -> str:
    """Format milliseconds as a WebVTT timestamp: HH:MM:SS.mmm."""
    return format_timestamp_srt(ms).replace(",", ".")


class SubtitleExporter(ABC):
    """Base class for subtitle exporters."""

    format_name: str = "txt"
    extension: str = "txt"
    line_ending: str = "\n"

    @abstractmethod
    def render(self, subtitles: Sequence[Subtitle]) -> str:
        """Render the full subtitle document as a string."""

    def export(
        self, subtitles: Sequence[Subtitle], path: Path | str, utf8_bom: bool = False
    ) -> Path:
        path = Path(path)
        content = self.render(subtitles)
        encoding = "utf-8-sig" if utf8_bom else "utf-8"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding=encoding, newline="") as handle:
                handle.write(content)
        except OSError as exc:
            raise ExportError(f"Could not write export file: {exc}") from exc
        logger.info("Exported %d subtitles to %s (%s).", len(subtitles), path, self.format_name)
        return path


class SRTExporter(SubtitleExporter):
    format_name = "srt"
    extension = "srt"
    line_ending = "\r\n"

    def render(self, subtitles: Sequence[Subtitle]) -> str:
        blocks: list[str] = []
        for number, sub in enumerate(subtitles, start=1):
            start = format_timestamp_srt(sub.start_ms)
            end = format_timestamp_srt(sub.end_ms)
            text = sub.text.strip().replace("\r\n", "\n").replace("\n", "\r\n")
            if not text.replace("\r\n", "").strip():
                continue  # empty entries would produce invalid blocks
            blocks.append(f"{number}\r\n{start} --> {end}\r\n{text}\r\n")
        return "\r\n".join(blocks)  # blank line between entries


class VTTExporter(SubtitleExporter):
    format_name = "vtt"
    extension = "vtt"

    def render(self, subtitles: Sequence[Subtitle]) -> str:
        lines: list[str] = ["WEBVTT", ""]
        for sub in subtitles:
            text = sub.text.strip()
            if not text:
                continue
            lines.append(f"{format_timestamp_vtt(sub.start_ms)} --> {format_timestamp_vtt(sub.end_ms)}")
            lines.append(text)
            lines.append("")
        return "\n".join(lines)


class TXTExporter(SubtitleExporter):
    format_name = "txt"
    extension = "txt"

    def render(self, subtitles: Sequence[Subtitle]) -> str:
        paragraphs = [sub.text.replace("\n", " ").strip() for sub in subtitles]
        return "\n".join(p for p in paragraphs if p) + "\n"


class JSONExporter(SubtitleExporter):
    format_name = "json"
    extension = "json"

    def render(self, subtitles: Sequence[Subtitle]) -> str:
        payload = {"subtitles": [sub.to_dict() for sub in subtitles]}
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


_EXPORTERS: dict[str, type[SubtitleExporter]] = {
    "srt": SRTExporter,
    "vtt": VTTExporter,
    "txt": TXTExporter,
    "json": JSONExporter,
}


def supported_formats() -> list[str]:
    return sorted(_EXPORTERS)


def get_exporter(fmt: str) -> SubtitleExporter:
    key = fmt.lower().strip(".")
    if key not in _EXPORTERS:
        raise ExportError(
            f"Unsupported export format '{fmt}'. Supported: {', '.join(supported_formats())}"
        )
    return _EXPORTERS[key]()


def export_subtitles(
    subtitles: Sequence[Subtitle],
    path: Path | str,
    fmt: str,
    utf8_bom: bool = False,
) -> Path:
    """Write subtitles to ``path`` in the requested format."""
    return get_exporter(fmt).export(subtitles, path, utf8_bom=utf8_bom)
