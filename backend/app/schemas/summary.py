"""Summary schemas: LLM video summary from saved subtitles (local Ollama)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SummarizeJobRequest(BaseModel):
    """Request of POST /jobs/{job_id}/summarize."""

    #: Override the configured model for this request.
    model: str | None = Field(default=None, max_length=100)
    #: Output language; None = infer from the job's detected language.
    language: Literal["en", "th"] | None = None


class SummaryKeyPointOut(BaseModel):
    """One key point, anchored to its cue (time_ms may be null)."""

    time_ms: int | None
    text: str


class SummaryOut(BaseModel):
    """Summary result - persisted server-side under the job's transcripts."""

    job_id: str
    model: str
    language: str
    summary: str
    key_points: list[SummaryKeyPointOut]
    cue_count: int
    generated_at: datetime
