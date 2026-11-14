"""Cleanup schemas: LLM subtitle text cleanup via a local Ollama server."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CleanupMode = Literal["punctuation", "casing", "fillers", "fluency", "thai_polish"]


class CleanupSubtitlesRequest(BaseModel):
    """Request of POST /jobs/{job_id}/subtitles/cleanup."""

    modes: list[CleanupMode] = Field(min_length=1)
    #: Override the configured model for this request.
    model: str | None = Field(default=None, max_length=100)


class CleanedTextItem(BaseModel):
    """One cleaned cue, aligned by 1-based subtitle index."""

    index: int
    text: str


class CleanupSubtitlesResponse(BaseModel):
    """Cleaned texts for the job's current subtitle list.

    The editor applies them client-side (single undo step); auto-save
    persists them like any other edit. Timestamps are never part of this.
    """

    job_id: str
    model: str
    modes: list[CleanupMode]
    cleaned: int
    total: int
    subtitles: list[CleanedTextItem]
