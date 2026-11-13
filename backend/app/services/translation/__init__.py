"""Subtitle translation services (Google Cloud Translation + Ollama)."""

from app.services.translation.base import (
    FALLBACK_LANGUAGES,
    TranslationResult,
    TranslationServiceError,
)
from app.services.translation.google_translate import (
    GoogleTranslateClient,
    is_translation_configured,
    make_translator,
)
from app.services.translation.ollama_translate import (
    OllamaTranslateClient,
    make_ollama_translator,
)

__all__ = [
    "FALLBACK_LANGUAGES",
    "GoogleTranslateClient",
    "OllamaTranslateClient",
    "TranslationResult",
    "TranslationServiceError",
    "is_translation_configured",
    "make_ollama_translator",
    "make_translator",
]
