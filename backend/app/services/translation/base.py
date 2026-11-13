"""Shared, backend-neutral types for the translation engines.

Both the Google Cloud Translation client (``google_translate.py``) and the
Ollama TranslateGemma client (``ollama_translate.py``) duck-type the same
call shape - ``translate(texts, target, source) -> TranslationResult`` and
raise :class:`TranslationServiceError` with an HTTP status + clean message -
so no ABC is needed; these shared types live here so neither client imports
from the other.
"""

from __future__ import annotations

from dataclasses import dataclass


class TranslationServiceError(Exception):
    """Raised with an HTTP status + clean user-facing message."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass
class TranslationResult:
    """Translated texts aligned 1:1 with the input list + usage metrics."""

    texts: list[str]
    detected_source_language: str | None = None
    #: characters actually sent for translation (observability; Google meters
    #: these, Ollama just reports them)
    characters_sent: int = 0
    #: number of HTTP requests made (one per batch, plus any fallback retries)
    requests: int = 0


def is_valid_language_code(code: str) -> bool:
    """Loose BCP-47-ish check: ``th`` / ``zh-CN`` style codes only."""
    parts = code.split("-")
    if not (1 <= len(parts) <= 2) or not all(parts):
        return False
    if not (2 <= len(parts[0]) <= 3 and parts[0].isalpha()):
        return False
    return len(parts) == 1 or (2 <= len(parts[1]) <= 8 and parts[1].replace("_", "").isalnum())


#: Curated fallback catalog shown when the Google API key is not configured
#: (or the live supported-languages call fails).  ``native`` is the endonym
#: shown in the UI alongside the English name.  Shared with the Ollama engine
#: for language names/labels.
FALLBACK_LANGUAGES: list[dict[str, str]] = [
    {"code": "th", "name": "Thai", "native": "ไทย"},
    {"code": "en", "name": "English", "native": "English"},
    {"code": "zh-CN", "name": "Chinese (Simplified)", "native": "简体中文"},
    {"code": "zh-TW", "name": "Chinese (Traditional)", "native": "繁體中文"},
    {"code": "ja", "name": "Japanese", "native": "日本語"},
    {"code": "ko", "name": "Korean", "native": "한국어"},
    {"code": "vi", "name": "Vietnamese", "native": "Tiếng Việt"},
    {"code": "id", "name": "Indonesian", "native": "Bahasa Indonesia"},
    {"code": "ms", "name": "Malay", "native": "Bahasa Melayu"},
    {"code": "km", "name": "Khmer", "native": "ខ្មែរ"},
    {"code": "lo", "name": "Lao", "native": "ລາວ"},
    {"code": "my", "name": "Burmese", "native": "မြန်မာ"},
    {"code": "de", "name": "German", "native": "Deutsch"},
    {"code": "fr", "name": "French", "native": "Français"},
    {"code": "es", "name": "Spanish", "native": "Español"},
    {"code": "pt", "name": "Portuguese", "native": "Português"},
    {"code": "it", "name": "Italian", "native": "Italiano"},
    {"code": "nl", "name": "Dutch", "native": "Nederlands"},
    {"code": "ru", "name": "Russian", "native": "Русский"},
    {"code": "uk", "name": "Ukrainian", "native": "Українська"},
    {"code": "pl", "name": "Polish", "native": "Polski"},
    {"code": "tr", "name": "Turkish", "native": "Türkçe"},
    {"code": "ar", "name": "Arabic", "native": "العربية"},
    {"code": "fa", "name": "Persian", "native": "فارسی"},
    {"code": "hi", "name": "Hindi", "native": "हिन्दी"},
    {"code": "bn", "name": "Bengali", "native": "বাংলা"},
    {"code": "ta", "name": "Tamil", "native": "தமிழ்"},
    {"code": "ur", "name": "Urdu", "native": "اردو"},
    {"code": "tl", "name": "Filipino", "native": "Filipino"},
]
