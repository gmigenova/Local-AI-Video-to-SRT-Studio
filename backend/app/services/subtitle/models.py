"""Subtitle data model (section 6.2).

Timestamps are integer milliseconds everywhere internally; conversion to
SRT/VTT timestamp strings happens only at export time.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Subtitle:
    """A single editable subtitle entry."""

    index: int
    start_ms: int
    end_ms: int
    text: str
    original_text: str
    is_edited: bool = False

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "text": self.text,
            "original_text": self.original_text,
            "is_edited": self.is_edited,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> Subtitle:
        return cls(
            index=int(payload["index"]),
            start_ms=int(payload["start_ms"]),
            end_ms=int(payload["end_ms"]),
            text=payload.get("text", ""),
            original_text=payload.get("original_text", payload.get("text", "")),
            is_edited=bool(payload.get("is_edited", False)),
        )


@dataclass(frozen=True)
class SubtitleWarning:
    """A quality-check finding attached to one subtitle (section 11.6)."""

    subtitle_index: int | None
    code: str
    message: str

    def __str__(self) -> str:
        target = f"#{self.subtitle_index}" if self.subtitle_index is not None else "global"
        return f"[{target}] {self.code}: {self.message}"
