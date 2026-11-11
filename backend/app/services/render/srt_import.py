"""External SRT import for burn-in renders.

Validates and normalises a user-supplied ``.srt`` file before it is staged
for rendering:

- decoding: UTF-8 (with or without BOM) first, then Thai legacy TIS-874 /
  windows-874 - subtitles produced on old Thai tools are often not UTF-8;
- parsing: tolerant SRT block parser (CRLF, missing block indexes, ``.``
  instead of ``,`` in timestamps, hours may be one digit);
- the normalised UTF-8 text is what gets burned, so libass never sees a
  legacy encoding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.errors import VideoToSrtError

#: generous ceiling for a subtitle sidecar file (bytes)
MAX_SRT_BYTES = 10 * 1024 * 1024

_TIMESTAMP_RE = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)


class SrtImportError(VideoToSrtError):
    """The supplied SRT file is unusable. Message is safe to show users."""


@dataclass(frozen=True)
class ImportedCue:
    start_ms: int
    end_ms: int
    text: str


def decode_srt_bytes(data: bytes) -> str:
    """Decode SRT bytes: UTF-8 first, then Thai windows-874 (TIS-874)."""
    if len(data) > MAX_SRT_BYTES:
        raise SrtImportError("The subtitle file is larger than 10 MB.")
    if not data.strip():
        raise SrtImportError("The subtitle file is empty.")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp874")
    except UnicodeDecodeError as exc:  # pragma: no cover - cp874 accepts almost everything
        raise SrtImportError(
            "The subtitle file is neither UTF-8 nor Thai (TIS-874) text."
        ) from exc


def parse_srt(content: str) -> list[ImportedCue]:
    """Parse SRT text into cues. Raises SrtImportError for unusable files.

    Tolerances: blank-line or line-per-block variants, missing block
    indexes, ``.`` milliseconds separator, CR line endings, BOM.
    """
    text = content.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    cues: list[ImportedCue] = []
    errors = 0

    blocks = re.split(r"\n{2,}", text)
    for block in blocks:
        lines = [line for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        # find the timestamp line (usually the 2nd, but indexes may be absent)
        ts_index = next(
            (i for i, line in enumerate(lines) if _TIMESTAMP_RE.search(line)), None
        )
        if ts_index is None:
            errors += 1
            continue
        match = _TIMESTAMP_RE.search(lines[ts_index])
        assert match is not None  # guaranteed by the search above
        start_ms = _ts_to_ms(match.group(1), match.group(2), match.group(3), match.group(4))
        end_ms = _ts_to_ms(match.group(5), match.group(6), match.group(7), match.group(8))
        cue_text = "\n".join(lines[ts_index + 1 :]).strip()
        if end_ms <= start_ms or not cue_text:
            errors += 1
            continue
        cues.append(ImportedCue(start_ms=start_ms, end_ms=end_ms, text=cue_text))

    if not cues:
        raise SrtImportError(
            "No valid subtitle cues were found. Expected SRT blocks such as "
            "'1\\n00:00:01,000 --> 00:00:03,000\\nHello'."
        )
    if errors:
        # keep going, but only when the bulk of the file parsed
        if errors > len(cues):
            raise SrtImportError(
                f"Most of the file could not be parsed ({errors} bad blocks, "
                f"{len(cues)} valid cues)."
            )
    return cues


def _ts_to_ms(hours: str, minutes: str, seconds: str, millis: str) -> int:
    return (
        (int(hours) * 3600 + int(minutes) * 60 + int(seconds)) * 1000
        + int(millis.ljust(3, "0"))
    )


def normalise_srt(data: bytes) -> tuple[str, int]:
    """Decode + validate + re-encode as clean UTF-8.

    Returns ``(normalised_text, cue_count)``. The normalised text is what
    should be written to disk for the burn; formatting (line breaks inside
    cues) is preserved.
    """
    content = decode_srt_bytes(data)
    cues = parse_srt(content)
    rebuilt = []
    for index, cue in enumerate(cues, start=1):
        rebuilt.append(
            f"{index}\n{_ms_to_ts(cue.start_ms)} --> {_ms_to_ts(cue.end_ms)}\n{cue.text}"
        )
    return "\n\n".join(rebuilt) + "\n", len(cues)


def _ms_to_ts(ms: int) -> str:
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"
