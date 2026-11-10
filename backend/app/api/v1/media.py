"""Media endpoints: upload, listing, stream inspection, video streaming (§10.4)."""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.core.errors import MediaValidationError
from app.database.base import get_db
from app.models.media_file import MediaFile
from app.repositories.media import MediaRepository
from app.schemas.media import AudioStreamOut, MediaOut, UploadResult
from app.services.media.ffprobe import probe_video
from app.services.media.upload_service import UploadService

router = APIRouter()

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
_STREAM_CHUNK = 4 * 1024 * 1024


def _get_media_or_404(db: Session, media_id: str) -> MediaFile:
    media = MediaRepository(db).get(media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Media file not found.")
    return media


@router.post("/media/upload", response_model=UploadResult, status_code=201)
def upload_media(
    request: Request,
    file: UploadFile = File(...),
    project_id: str = Form(...),
    audio_stream_index: int = Form(0),
    db: Session = Depends(get_db),
) -> UploadResult:
    content_length: int | None = None
    raw_length = request.headers.get("content-length")
    if raw_length and raw_length.isdigit():
        content_length = int(raw_length)
    try:
        media, info = UploadService(db).store(
            stream=file.file,
            original_name=file.filename or "upload",
            project_id=project_id,
            audio_stream_index=audio_stream_index,
            content_length=content_length,
        )
    finally:
        file.file.close()
    return UploadResult(
        media_id=media.id,
        filename=media.original_name,
        duration_ms=media.duration_ms,
        audio_streams=[
            AudioStreamOut(
                stream_index=s.stream_index,
                codec_name=s.codec_name,
                channels=s.channels,
                sample_rate=s.sample_rate,
                language=s.language,
            )
            for s in info.audio_streams
        ],
    )


@router.get("/media", response_model=list[MediaOut])
def list_media(project_id: str, db: Session = Depends(get_db)) -> list[MediaOut]:
    media_list = MediaRepository(db).list_for_project(project_id)
    return [MediaOut.model_validate(m) for m in media_list]


@router.get("/media/{media_id}", response_model=MediaOut)
def get_media(media_id: str, db: Session = Depends(get_db)) -> MediaOut:
    return MediaOut.model_validate(_get_media_or_404(db, media_id))


@router.get("/media/{media_id}/streams", response_model=list[AudioStreamOut])
def media_streams(media_id: str, db: Session = Depends(get_db)) -> list[AudioStreamOut]:
    """Re-probe the file and list its audio streams (for stream selection)."""
    media = _get_media_or_404(db, media_id)
    try:
        info = probe_video(media.file_path)
    except MediaValidationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return [
        AudioStreamOut(
            stream_index=s.stream_index,
            codec_name=s.codec_name,
            channels=s.channels,
            sample_rate=s.sample_rate,
            language=s.language,
        )
        for s in info.audio_streams
    ]


@router.get("/media/{media_id}/stream")
def stream_media(media_id: str, request: Request, db: Session = Depends(get_db)):
    """Serve the original video with HTTP Range support (video preview, §11.5)."""
    media = _get_media_or_404(db, media_id)
    path = Path(media.file_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Stored video file is missing.")
    size = path.stat().st_size
    media_type = mimetypes.guess_type(media.original_name)[0] or "video/mp4"

    range_header = request.headers.get("range")
    if range_header:
        match = _RANGE_RE.match(range_header)
        if match:
            start = int(match.group(1) or 0)
            end = int(match.group(2) or size - 1) if match.group(2) else size - 1
            end = min(end, size - 1)
            if start > end or start >= size:
                return Response(
                    status_code=416,
                    headers={"Content-Range": f"bytes */{size}"},
                )
            with open(path, "rb") as handle:
                handle.seek(start)
                data = handle.read(end - start + 1)
            return Response(
                content=data,
                status_code=206,
                media_type=media_type,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(len(data)),
                },
            )

    return FileResponse(path, media_type=media_type, headers={"Accept-Ranges": "bytes"})
