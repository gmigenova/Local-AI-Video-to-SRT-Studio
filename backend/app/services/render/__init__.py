"""Subtitle burn-in rendering: service layer (burner + queue manager)."""

from __future__ import annotations

from app.services.render.burner import (
    MP4_AUDIO_CODECS,
    RENDER_SRT_NAME,
    BurnResult,
    SubtitleBurner,
    build_burn_args,
    sanitize_font_name,
)
from app.services.render.manager import (
    RenderManager,
    get_render_manager,
    set_render_manager,
)
from app.services.render.srt_import import (
    MAX_SRT_BYTES,
    ImportedCue,
    SrtImportError,
    decode_srt_bytes,
    normalise_srt,
    parse_srt,
)

__all__ = [
    "BurnResult",
    "ImportedCue",
    "MAX_SRT_BYTES",
    "MP4_AUDIO_CODECS",
    "RENDER_SRT_NAME",
    "RenderManager",
    "SrtImportError",
    "SubtitleBurner",
    "build_burn_args",
    "decode_srt_bytes",
    "get_render_manager",
    "normalise_srt",
    "parse_srt",
    "sanitize_font_name",
    "set_render_manager",
]
