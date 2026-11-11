"""Video render (subtitle burn-in) schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RenderCreateRequest(BaseModel):
    font_name: str | None = Field(
        default=None,
        max_length=100,
        description="Optional font override for burned subtitles (e.g. a Thai font).",
    )


class RenderCreated(BaseModel):
    render_id: str
    status: str


class RenderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    render_id: str = Field(validation_alias="id")
    job_id: str
    status: str
    progress: float
    current_stage: str | None
    error_message: str | None
    font_name: str | None
    file_size: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
