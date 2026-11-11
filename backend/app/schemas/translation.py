"""Translation schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

#: How the translated text lands in the editor.
#   - ``replace``: the translated text replaces the cue text.
#   - ``dual``:    the translation is appended below the original text
#                  (bilingual subtitles).
TranslateMode = Literal["replace", "dual"]


class TranslateLanguageOut(BaseModel):
    code: str
    name: str


class TranslationInfoOut(BaseModel):
    """Response of GET /translation/languages."""

    configured: bool
    languages: list[TranslateLanguageOut]


class TranslateSubtitlesRequest(BaseModel):
    """Request of POST /jobs/{job_id}/subtitles/translate."""

    target_language: str = Field(min_length=2, max_length=10)
    source_language: str | None = None
    mode: TranslateMode = "replace"


class TranslatedTextItem(BaseModel):
    """One translated cue, aligned by 1-based subtitle index."""

    index: int
    text: str


class TranslationUsageOut(BaseModel):
    """Cumulative Google Cloud Translation usage for the current month."""

    period: str
    characters_sent: int
    words_sent: int
    texts_translated: int
    requests: int
    jobs: int
    #: configured monthly character budget; 0 = unlimited
    monthly_char_limit: int
    remaining_chars: int | None = None  # None when unlimited


class TranslateSubtitlesResponse(BaseModel):
    """Raw translations for the job's current subtitle list.

    The editor applies them client-side (single undo step); ``mode`` is
    echoed back so the UI knows how the texts were meant to be combined.
    """

    job_id: str
    target_language: str
    source_language: str | None
    detected_source_language: str | None
    mode: TranslateMode
    translated: int
    total: int
    subtitles: list[TranslatedTextItem]
    #: usage AFTER this operation was recorded
    usage: TranslationUsageOut
