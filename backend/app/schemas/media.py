"""Media schemas. Internal filesystem paths are never exposed (§16)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AudioStreamOut(BaseModel):
    stream_index: int
    codec_name: str
    channels: int | None
    sample_rate: int | None
    language: str | None


class MediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    original_name: str
    stored_name: str
    file_size: int
    duration_ms: int | None
    video_codec: str | None
    audio_codec: str | None
    width: int | None
    height: int | None
    audio_stream_index: int
    created_at: datetime


class MediaUpdate(BaseModel):
    """PATCH /media/{id}: select the audio stream (absolute stream index)."""

    stream_index: int


class UploadResult(BaseModel):
    """Response for POST /media/upload (section 10.4) + live stream list."""

    media_id: str
    filename: str
    duration_ms: int | None
    status: str = "uploaded"
    audio_streams: list[AudioStreamOut] = []
