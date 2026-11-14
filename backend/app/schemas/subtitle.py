"""Subtitle schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SubtitleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    subtitle_index: int
    start_ms: int
    end_ms: int
    text: str
    original_text: str
    is_edited: bool
    speaker: str | None = None
    updated_at: datetime


class SubtitleUpdate(BaseModel):
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    text: str | None = None


class SubtitleBulkItem(BaseModel):
    id: str
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    text: str | None = None


class BulkSubtitleUpdate(BaseModel):
    updates: list[SubtitleBulkItem]


class SubtitleSyncItem(BaseModel):
    """One subtitle in an editor sync: order = list order (renumbered 1..N)."""

    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    text: str
    original_text: str | None = None
    is_edited: bool = False
    speaker: str | None = Field(default=None, max_length=64)


class SubtitleSyncRequest(BaseModel):
    """Full-state save from the subtitle editor (add/delete/edit/reorder)."""

    subtitles: list[SubtitleSyncItem]
