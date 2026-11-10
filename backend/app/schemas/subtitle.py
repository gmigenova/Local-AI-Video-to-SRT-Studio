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
