"""Transcription job schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class JobCreateRequest(BaseModel):
    media_id: str
    model: str = "large-v3"
    language: str | None = Field(default=None, max_length=20)
    settings: dict = Field(default_factory=dict)


class JobCreated(BaseModel):
    job_id: str
    status: str


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str = Field(validation_alias="id")
    media_id: str
    status: str
    model_name: str
    language: str | None
    detected_language: str | None
    language_probability: float | None
    progress: float
    current_stage: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class JobStatusOut(BaseModel):
    """GET /jobs/{job_id} response (section 10.6)."""

    job_id: str
    status: str
    progress: float
    current_stage: str | None
    detected_language: str | None
