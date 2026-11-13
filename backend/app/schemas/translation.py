"""Translation schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

#: How the translated text lands in the editor.
#   - ``replace``: the translated text replaces the cue text.
#   - ``dual``:    the translation is appended below the original text
#                  (bilingual subtitles).
TranslateMode = Literal["replace", "dual"]

#: Which translation engine to use (Ollama = local TranslateGemma, free).
TranslateEngine = Literal["google", "ollama"]


class TranslateLanguageOut(BaseModel):
    code: str
    name: str


class GoogleEngineOut(BaseModel):
    """Google Cloud Translation availability."""

    configured: bool


class OllamaEngineOut(BaseModel):
    """Ollama (TranslateGemma) availability + installed models."""

    available: bool
    url: str
    model: str
    models: list[str]


class TranslationEnginesOut(BaseModel):
    google: GoogleEngineOut
    ollama: OllamaEngineOut


class TranslationInfoOut(BaseModel):
    """Response of GET /translation/languages.

    ``configured``/``languages`` are the legacy Google-oriented fields
    (kept for compatibility); ``engines`` carries per-engine status.
    """

    configured: bool
    languages: list[TranslateLanguageOut]
    engines: TranslationEnginesOut


class TranslateSubtitlesRequest(BaseModel):
    """Request of POST /jobs/{job_id}/subtitles/translate."""

    engine: TranslateEngine = "google"
    target_language: str = Field(min_length=2, max_length=10)
    source_language: str | None = None
    mode: TranslateMode = "replace"
    #: Ollama-only: override the configured model for this request.
    model: str | None = Field(default=None, max_length=100)


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
    ``usage`` is None for the Ollama engine (local, not metered).
    """

    job_id: str
    engine: TranslateEngine
    model: str | None = None
    target_language: str
    source_language: str | None
    detected_source_language: str | None
    mode: TranslateMode
    translated: int
    total: int
    subtitles: list[TranslatedTextItem]
    usage: TranslationUsageOut | None = None
