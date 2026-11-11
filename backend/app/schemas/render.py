"""Video render (subtitle burn-in) schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RenderCreated(BaseModel):
    render_id: str
    status: str
    source: str = "editor"
    subtitle_count: int | None = None


class RenderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    render_id: str = Field(validation_alias="id")
    job_id: str
    status: str
    source: str
    progress: float
    current_stage: str | None
    error_message: str | None
    font_name: str | None
    file_size: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
