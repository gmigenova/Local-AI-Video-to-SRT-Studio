"""Ollama TranslateGemma client: free, fully local subtitle translation.

Talks to a local Ollama server (default ``http://127.0.0.1:11434``) with
stdlib ``urllib`` only.  Uses the official single-user-message prompt
template from https://ollama.com/library/translategemma - the source
language is baked into the prompt (the model has no auto-detect).

Cues are sent in batches (one line per cue) and the response must come
back with the same number of lines; on a line-count mismatch the batch is
retried cue by cue.  All failures raise :class:`TranslationServiceError`
with a clean, user-facing message (§16).
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from app.core.config import Settings, get_settings
from app.services.translation.base import (
    FALLBACK_LANGUAGES,
    TranslationResult,
    TranslationServiceError,
    is_valid_language_code,
)

logger = logging.getLogger(__name__)

_CHAT_PATH = "/api/chat"
_TAGS_PATH = "/api/tags"

#: Conservative per-request caps - LLM latency grows with batch size.
_MAX_CUES_PER_REQUEST = 25
_MAX_CHARS_PER_REQUEST = 3000

#: Short probe timeout so a dead Ollama never stalls the languages endpoint.
_TAGS_TIMEOUT_SECONDS = 2.5

#: TranslateGemma uses BCP-47 script codes where the shared catalog uses
#: Google-style region codes.
_CODE_ALIASES = {"zh-CN": "zh-Hans", "zh-TW": "zh-Hant"}

#: Official TranslateGemma prompt (ollama.com/library/translategemma), with
#: TWO blank lines before the text.  ``batch_note`` adds a line-count
#: instruction for multi-cue batches to keep the output line-aligned.
_PROMPT_TEMPLATE = (
    "You are a professional {source_name} ({source_code}) to "
    "{target_name} ({target_code}) translator. "
    "Your goal is to accurately convey the meaning and nuances of the "
    "original text while adhering to the target grammar, vocabulary, and "
    "cultural sensitivities. "
    "Produce only the {target_name} translation, without any additional "
    "explanations or commentary. "
    "Please translate the following {source_name} text into {target_name}:"
    "{batch_note}\n\n\n{text}"
)

_LANGUAGE_NAMES = {item["code"]: item["name"] for item in FALLBACK_LANGUAGES}


def language_label(code: str) -> tuple[str, str]:
    """(english_name, translategemma_code) for a catalog language code."""
    return _LANGUAGE_NAMES.get(code, code), _CODE_ALIASES.get(code, code)


class OllamaTranslateClient:
    """TranslateGemma via a local Ollama server (``/api/chat``)."""

    def __init__(self, base_url: str, model: str, timeout_seconds: float = 300.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds

    @property
    def model_name(self) -> str:
        return self._model

    # ---------------------------------------------------------------- api
    def translate(
        self,
        texts: list[str],
        target_language: str,
        source_language: str | None = None,
    ) -> TranslationResult:
        """Translate ``texts`` (order preserved); empty cues pass through.

        The source language is required - it is part of the prompt template.
        """
        if not is_valid_language_code(target_language):
            raise TranslationServiceError(
                400, f"Unsupported target language code: '{target_language}'."
            )
        if source_language is None:
            raise TranslationServiceError(
                400,
                "Ollama translation needs an explicit source language; "
                "auto-detect is not supported.",
            )
        if not is_valid_language_code(source_language):
            raise TranslationServiceError(
                400, f"Unsupported source language code: '{source_language}'."
            )

        results = [""] * len(texts)
        request_count = 0
        characters_sent = 0

        for positions, batch in self._batches(texts):
            content = self._chat(self._build_prompt(batch, source_language, target_language))
            request_count += 1
            characters_sent += sum(len(cue) for cue in batch)

            lines = self._split_lines(content)
            if len(lines) == len(batch):
                for slot, line in zip(positions, lines, strict=True):
                    results[slot] = line
                continue

            # line-count mismatch -> fall back to one request per cue
            logger.info(
                "Ollama batch alignment mismatch (%d cues, %d lines) - falling back to per-cue",
                len(batch),
                len(lines),
            )
            for slot, cue in zip(positions, batch, strict=True):
                single = self._chat(self._build_prompt([cue], source_language, target_language))
                request_count += 1
                joined = " ".join(part.strip() for part in single.splitlines() if part.strip())
                if not joined:
                    raise TranslationServiceError(
                        502,
                        "Ollama returned misaligned translations. "
                        "Try a different model or shorter subtitles.",
                    )
                results[slot] = joined

        return TranslationResult(
            texts=results,
            detected_source_language=None,  # source is explicit
            characters_sent=characters_sent,
            requests=request_count,
        )

    def list_models(self) -> list[str]:
        """Installed Ollama model names (sorted); empty list = none pulled."""
        payload = self._request(_TAGS_PATH, timeout=_TAGS_TIMEOUT_SECONDS)
        names = sorted(
            {
                str(item.get("name", "")).strip()
                for item in payload.get("models", [])
                if str(item.get("name", "")).strip()
            }
        )
        return names

    # ------------------------------------------------------------ helpers
    def _build_prompt(self, batch: list[str], source: str, target: str) -> str:
        source_name, source_code = language_label(source)
        target_name, target_code = language_label(target)
        # one line per cue keeps the output line-aligned with the batch
        text = "\n".join(" ".join(cue.split()) for cue in batch)
        note = (
            ""
            if len(batch) == 1
            else (
                f" The text consists of {len(batch)} subtitle lines. Translate "
                f"each line separately and output exactly {len(batch)} lines "
                "in the same order."
            )
        )
        return _PROMPT_TEMPLATE.format(
            source_name=source_name,
            source_code=source_code,
            target_name=target_name,
            target_code=target_code,
            batch_note=note,
            text=text,
        )

    @staticmethod
    def _split_lines(content: str) -> list[str]:
        lines = [line.strip() for line in content.strip().split("\n")]
        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()
        return lines

    def _batches(
        self, texts: list[str]
    ) -> list[tuple[list[int], list[str]]]:
        """Split non-empty cues into request-sized ``(positions, batch)`` pairs."""
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
            stripped = " ".join(text.split())  # one line per cue
            if not stripped:
                continue  # empty cues pass through untranslated
            if len(batch) >= _MAX_CUES_PER_REQUEST or (
                chars + len(stripped) > _MAX_CHARS_PER_REQUEST and batch
            ):
                flush()
            positions.append(i)
            batch.append(stripped)
            chars += len(stripped)
        flush()
        return batches

    def _chat(self, prompt: str) -> str:
        payload = self._request(
            _CHAT_PATH,
            {
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0},
            },
        )
        content = str(payload.get("message", {}).get("content", "")).strip()
        if not content:
            raise TranslationServiceError(502, "Ollama returned an unreadable response.")
        return content

    def _request(
        self, path: str, body: dict | None = None, timeout: float | None = None
    ) -> dict:
        """Single network touchpoint (GET when ``body`` is None, else POST)."""
        url = f"{self._base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(  # noqa: S310 - configured local URL
            url,
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"} if data else {},
            method="POST" if data is not None else "GET",
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 - configured local URL
                request, timeout=timeout or self._timeout
            ) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning("Ollama request failed (%s): %s", path, exc)
            raise TranslationServiceError(
                502, "Could not reach Ollama. Check that it is running at the configured OLLAMA_URL."
            ) from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("Ollama returned non-JSON body (%d bytes)", len(raw))
            raise TranslationServiceError(502, "Ollama returned an unreadable response.") from exc

    def _http_error(self, exc: urllib.error.HTTPError) -> TranslationServiceError:
        detail = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
            parsed = json.loads(body)
            detail = str(parsed.get("error", body[:200]))
        except (OSError, ValueError):
            pass
        logger.warning("Ollama HTTP %s: %s", exc.code, detail)
        if exc.code == 404:
            return TranslationServiceError(
                404,
                f"Model '{self._model}' is not installed in Ollama. "
                f"Run 'ollama pull {self._model}' or pick another model.",
            )
        return TranslationServiceError(
            502, "Ollama returned an error while translating. Check the backend logs."
        )


def make_ollama_translator(
    settings: Settings | None = None, model: str | None = None
) -> OllamaTranslateClient:
    """Client from settings (always constructible - availability is checked
    live via :meth:`OllamaTranslateClient.list_models`, not at construction)."""
    cfg = settings or get_settings()
    return OllamaTranslateClient(
        base_url=cfg.ollama_url,
        model=model or cfg.ollama_translate_model,
        timeout_seconds=cfg.ollama_timeout_seconds,
    )
