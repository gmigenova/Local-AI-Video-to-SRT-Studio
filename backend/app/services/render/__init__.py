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

__all__ = [
    "BurnResult",
    "MP4_AUDIO_CODECS",
    "RENDER_SRT_NAME",
    "RenderManager",
    "SubtitleBurner",
    "build_burn_args",
    "get_render_manager",
    "sanitize_font_name",
    "set_render_manager",
]
