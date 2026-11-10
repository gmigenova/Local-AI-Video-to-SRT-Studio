"""Media upload service (§8, §10.4, §17).

- Uploads stream to ``storage/uploads/{media_id}/original{ext}`` - generated
  UUID paths only, never the original filename (§8).
- Extension allowlist + size limit enforced up front and during the stream
  copy; content is validated with FFprobe after landing on disk.
- The original file is never modified afterwards.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import BinaryIO

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import (
    MediaValidationError,
)
from app.models.media_file import MediaFile
from app.repositories.media import MediaRepository
from app.repositories.projects import ProjectsRepository
from app.services.media.ffprobe import (
    MediaInfo,
    is_supported_extension,
    probe_video,
)

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 1024 * 1024


class UploadRejected(Exception):
    """Raised with an HTTP status + clean message (no internals leaked)."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class UploadService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    @property
    def max_bytes(self) -> int:
        return int(self.settings.max_upload_size_gb * 1024**3)

    def store(
        self,
        stream: BinaryIO,
        original_name: str,
        project_id: str,
        audio_stream_index: int = 0,
        content_length: int | None = None,
    ) -> tuple[MediaFile, MediaInfo]:
        """Validate, stream to storage and register a media file.

        Raises:
            UploadRejected: with a 4xx status for user errors.
        """
        if ProjectsRepository(self.db).get(project_id) is None:
            raise UploadRejected(404, "Project not found.")

        suffix = Path(original_name).suffix
        if not is_supported_extension(suffix):
            raise UploadRejected(
                400,
                f"Unsupported file type '{suffix or '(none)'}'. "
                "Supported: mp4, mkv, avi, mov, webm, m4v.",
            )
        if content_length is not None and content_length > self.max_bytes:
            raise UploadRejected(413, "File exceeds the upload size limit.")

        media_repo = MediaRepository(self.db)
        # reserve the row id first so the storage path uses the media UUID
        media = media_repo.create(
            project_id=project_id,
            original_name=Path(original_name).name,
            stored_name="pending",
            file_path="pending",
            audio_stream_index=audio_stream_index,
        )
        dest_dir = self.settings.storage_subdir("uploads") / media.id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"original{suffix}"

        try:
            written = self._copy_with_limit(stream, dest)
            info = probe_video(dest, ffprobe_path=self.settings.ffprobe_path)
        except UploadRejected:
            self._cleanup(media_repo, media, dest_dir)
            raise
        except MediaValidationError as exc:
            self._cleanup(media_repo, media, dest_dir)
            raise UploadRejected(400, str(exc)) from exc
        except OSError as exc:
            self._cleanup(media_repo, media, dest_dir)
            raise UploadRejected(507, "Disk write failed while storing upload.") from exc

        if not 0 <= audio_stream_index < len(info.audio_streams):
            self._cleanup(media_repo, media, dest_dir)
            raise UploadRejected(
                400,
                f"Audio stream #{audio_stream_index} not found "
                f"(file has {len(info.audio_streams)}).",
            )

        media.stored_name = dest.name
        media.file_path = str(dest)
        media.file_size = written
        media.duration_ms = info.duration_ms
        media.video_codec = info.video_codec
        media.audio_codec = info.audio_streams[0].codec_name
        media.width = info.width
        media.height = info.height
        self.db.commit()
        logger.info(
            "Stored upload %s (%d bytes, %d ms) as %s",
            media.original_name, written, info.duration_ms or 0, media.id,
        )
        return media, info

    def _copy_with_limit(self, stream: BinaryIO, dest: Path) -> int:
        written = 0
        try:
            with open(dest, "wb") as out:
                while True:
                    chunk = stream.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > self.max_bytes:
                        raise UploadRejected(413, "File exceeds the upload size limit.")
                    out.write(chunk)
        except Exception:
            dest.unlink(missing_ok=True)
            raise
        if written == 0:
            dest.unlink(missing_ok=True)
            raise UploadRejected(400, "Uploaded file is empty.")
        return written

    def _cleanup(self, media_repo: MediaRepository, media: MediaFile, dest_dir: Path) -> None:
        shutil.rmtree(dest_dir, ignore_errors=True)
        self.db.delete(media)
        self.db.commit()
