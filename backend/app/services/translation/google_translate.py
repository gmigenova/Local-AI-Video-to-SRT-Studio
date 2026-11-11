"""Google Cloud Translation API (Basic, v2) client for subtitle translation.

Uses the plain REST endpoint with an API key so no extra SDK dependency is
needed (stdlib ``urllib`` only).  Texts are translated as plain text
(``format=text``) so subtitle line breaks survive, and requests are batched
within Google's per-request limits (max 128 segments; keep well under that).

All failures raise :class:`TranslationServiceError` with a clean, user-facing
message plus an HTTP status - details are logged by the caller, never leaked
to the client (§16).
"""

from __future__ import annotations

import html
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

#: Translation API v2 endpoints (Basic edition, API-key auth).
_TRANSLATE_URL = "https://translation.googleapis.com/language/translate/v2"
_LANGUAGES_URL = f"{_TRANSLATE_URL}/languages"

#: Conservative per-request limits (Google allows up to 128 segments).
_MAX_TEXTS_PER_REQUEST = 64
_MAX_CHARS_PER_REQUEST = 4000

#: Curated fallback catalog shown when the API key is not configured (or the
#: live supported-languages call fails).  ``native`` is the endonym shown in
#: the UI alongside the English name.
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


class TranslationServiceError(Exception):
    """Raised with an HTTP status + clean user-facing message."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass
class TranslationResult:
    """Translated texts aligned 1:1 with the input list + detected source."""

    texts: list[str]
    detected_source_language: str | None = None


def _is_valid_language_code(code: str) -> bool:
    """Loose BCP-47-ish check: ``th`` / ``zh-CN`` style codes only."""
    parts = code.split("-")
    if not (1 <= len(parts) <= 2) or not all(parts):
        return False
    if not (2 <= len(parts[0]) <= 3 and parts[0].isalpha()):
        return False
    return len(parts) == 1 or (2 <= len(parts[1]) <= 8 and parts[1].replace("_", "").isalnum())


class GoogleTranslateClient:
    """Minimal Translation API v2 client (API-key auth, plain REST)."""

    def __init__(self, api_key: str, timeout_seconds: float = 30.0) -> None:
        self._api_key = api_key
        self._timeout = timeout_seconds

    # ------------------------------------------------------------------ api
    def translate(
        self,
        texts: list[str],
        target_language: str,
        source_language: str | None = None,
    ) -> TranslationResult:
        """Translate ``texts`` into ``target_language`` (order preserved).

        Empty strings are passed through untouched (the API rejects them).
        """
        if not _is_valid_language_code(target_language):
            raise TranslationServiceError(
                400, f"Unsupported target language code: '{target_language}'."
            )
        if source_language is not None and not _is_valid_language_code(source_language):
            raise TranslationServiceError(
                400, f"Unsupported source language code: '{source_language}'."
            )

        results = [""] * len(texts)
        detected: str | None = None
        translated_count = 0

        for positions, batch in self._batches(texts):
            payload = self._post(
                {
                    "q": batch,
                    "target": target_language,
                    "format": "text",
                    **({"source": source_language} if source_language else {}),
                }
            )
            translations = payload.get("data", {}).get("translations", [])
            if len(translations) != len(batch):
                raise TranslationServiceError(
                    502, "Google Translate returned an unexpected response."
                )
            for slot, entry in zip(positions, translations, strict=True):
                text = html.unescape(str(entry.get("translatedText", "")))
                results[slot] = text.strip()
                translated_count += 1
            if detected is None:
                first = translations[0].get("detectedSourceLanguage")
                detected = str(first) if first else None

        return TranslationResult(texts=results, detected_source_language=detected)

    def list_supported_languages(self, display_language: str = "en") -> list[dict[str, str]]:
        """Languages Google reports as supported: ``[{code, name}]``."""
        payload = self._post({"target": display_language}, endpoint=_LANGUAGES_URL)
        languages = payload.get("data", {}).get("languages", [])
        catalog = [
            {
                "code": str(item.get("language", "")).strip(),
                "name": str(item.get("name", "")).strip()
                or str(item.get("language", "")).strip(),
            }
            for item in languages
        ]
        if not catalog:
            raise TranslationServiceError(502, "Google Translate returned no languages.")
        return sorted(catalog, key=lambda item: item["name"].casefold())

    # -------------------------------------------------------------- helpers
    def _batches(
        self, texts: list[str]
    ) -> list[tuple[list[int], list[str]]]:
        """Split non-empty texts into API-sized batches.

        Returns a list of ``(original_positions, batch_texts)`` pairs so the
        results can be slotted back into their original order.
        """
        batches: list[tuple[list[int], list[str]]] = []
        positions: list[int] = []
        batch: list[str] = []
        chars = 0

        def flush() -> None:
            nonlocal positions, batch, chars
            if batch:
                batches.append((positions, batch))
            positions, batch, chars = [], [], 0

        for i, text in enumerate(texts):
            stripped = text.strip()
            if not stripped:  # API rejects empty strings; keep them as-is
                continue
            if len(batch) >= _MAX_TEXTS_PER_REQUEST or (
                chars + len(stripped) > _MAX_CHARS_PER_REQUEST and batch
            ):
                flush()
            positions.append(i)
            batch.append(stripped)
            chars += len(stripped)
        flush()
        return batches

    def _post(self, body: dict, endpoint: str = _TRANSLATE_URL) -> dict:
        request = urllib.request.Request(  # noqa: S310 - fixed https endpoint
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                # header auth keeps the key out of URLs / proxy logs
                "X-goog-api-key": self._api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning("Google Translate request failed: %s", exc)
            raise TranslationServiceError(
                502, "Could not reach Google Cloud Translation. Check your network."
            ) from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("Google Translate returned non-JSON body (%d bytes)", len(raw))
            raise TranslationServiceError(
                502, "Google Cloud Translation returned an unreadable response."
            ) from exc
        if "error" in payload:
            message = str(payload["error"].get("message", "Unknown API error."))
            logger.warning("Google Translate API error: %s", message)
            raise TranslationServiceError(502, "Google Cloud Translation rejected the request.")
        return payload

    def _http_error(self, exc: urllib.error.HTTPError) -> TranslationServiceError:
        detail = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
            detail = str(json.loads(body).get("error", {}).get("message", ""))
        except (OSError, ValueError, AttributeError):
            pass
        logger.warning("Google Translate HTTP %s: %s", exc.code, detail)
        if exc.code == 400:
            return TranslationServiceError(
                400, "Google Cloud Translation rejected the request (unsupported language?)."
            )
        if exc.code in (401, 403):
            return TranslationServiceError(
                401, "Google Cloud Translation rejected the API key. Check GOOGLE_TRANSLATE_API_KEY."
            )
        if exc.code == 429:
            return TranslationServiceError(
                429, "Google Cloud Translation quota exceeded. Try again later."
            )
        return TranslationServiceError(502, "Google Cloud Translation request failed.")


def is_translation_configured(settings: Settings | None = None) -> bool:
    return bool((settings or get_settings()).google_translate_api_key)


def make_translator(settings: Settings | None = None) -> GoogleTranslateClient | None:
    """Client from settings, or ``None`` when the API key is not configured."""
    cfg = settings or get_settings()
    if not cfg.google_translate_api_key:
        return None
    return GoogleTranslateClient(
        api_key=cfg.google_translate_api_key,
        timeout_seconds=cfg.google_translate_timeout_seconds,
    )
