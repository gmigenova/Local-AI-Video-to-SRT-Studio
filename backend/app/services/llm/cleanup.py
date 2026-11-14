"""LLM subtitle cleanup via a local Ollama server (stdlib only).

The cleanup pass proofreads subtitle *text* - punctuation, casing, filler
words, awkward phrasing - and never touches timing.  Cues are batched one
line per cue exactly like the Ollama translator (shared helpers in
``app.services.llm.batching``); a line-count mismatch falls back to one
request per cue.  All failures raise :class:`CleanupServiceError` with an
HTTP status + clean, user-facing message (§16).
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.core.config import Settings, get_settings
from app.services.llm.batching import (
    build_batches,
    split_lines,
    strip_enumeration_prefixes,
)

logger = logging.getLogger(__name__)

_CHAT_PATH = "/api/chat"

CleanupMode = Literal["punctuation", "casing", "fillers", "fluency", "thai_polish"]

#: Instruction fragments injected into the system prompt per selected mode.
MODE_INSTRUCTIONS: dict[str, str] = {
    "punctuation": (
        "Add missing punctuation (commas, periods, question marks) the way a "
        "native writer would for the subtitle's language."
    ),
    "casing": (
        "Fix letter casing: capitalise sentence starts and proper nouns "
        "(for scripts that use casing)."
    ),
    "fillers": (
        "Remove filler words and stutters ('um', 'uh', 'you know', repeated "
        "words) that add no meaning."
    ),
    "fluency": (
        "Smooth obviously awkward phrasing left over from transcription so "
        "the line reads naturally - without changing its meaning."
    ),
    "thai_polish": (
        "Polish Thai text: fix spacing between clauses, remove stray spaces "
        "inside words, and make the line easy to read at subtitle speed."
    ),
}

VALID_MODES: tuple[str, ...] = tuple(MODE_INSTRUCTIONS)

_SYSTEM_PROMPT = (
    "You are a professional subtitle proofreader. You clean up subtitle "
    "lines without changing what they say or their language.\n"
    "Fix ONLY these issues:\n{instructions}\n"
    "Rules:\n"
    "- Keep each line in the same language as its input.\n"
    "- Never merge or split lines: output exactly one cleaned line per "
    "input line.\n"
    "- Never translate, summarise, or answer the text.\n"
    "- Output plain lines only - no numbering, no quotes, no commentary."
)

_BATCH_NOTE = (
    " The text consists of {count} subtitle lines. Clean each line "
    "separately and output exactly {count} plain lines in the same order."
)


class CleanupServiceError(Exception):
    """Raised with an HTTP status + clean user-facing message."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass
class CleanupResult:
    """Cleaned texts aligned 1:1 with the input list."""

    texts: list[str]
    requests: int = 0


class OllamaCleanupClient:
    """Subtitle text cleanup via a local Ollama server (``/api/chat``)."""

    def __init__(self, base_url: str, model: str, timeout_seconds: float = 300.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds

    @property
    def model_name(self) -> str:
        return self._model

    # ---------------------------------------------------------------- api
    def cleanup(self, texts: list[str], modes: Sequence[str]) -> CleanupResult:
        """Proofread ``texts`` (order preserved); empty cues pass through."""
        unknown = [mode for mode in modes if mode not in MODE_INSTRUCTIONS]
        if unknown or not modes:
            raise CleanupServiceError(
                400,
                f"Unknown cleanup mode(s): {', '.join(unknown or ['<empty>'])}. "
                f"Valid modes: {', '.join(VALID_MODES)}.",
            )

        results = [""] * len(texts)
        request_count = 0

        for positions, batch in build_batches(texts):
            content = self._chat(self._build_user_prompt(batch), modes)
            request_count += 1

            lines = split_lines(content)
            if len(lines) == len(batch):
                for slot, line in zip(positions, strip_enumeration_prefixes(lines), strict=True):
                    results[slot] = line
                continue

            # line-count mismatch -> fall back to one request per cue
            logger.info(
                "Cleanup batch alignment mismatch (%d cues, %d lines) - "
                "falling back to per-cue",
                len(batch),
                len(lines),
            )
            for slot, cue in zip(positions, batch, strict=True):
                single = self._chat(self._build_user_prompt([cue]), modes)
                request_count += 1
                joined = " ".join(part.strip() for part in single.splitlines() if part.strip())
                if not joined:
                    raise CleanupServiceError(
                        502,
                        "Ollama returned misaligned cleanup results. "
                        "Try a different model or shorter subtitles.",
                    )
                results[slot] = joined

        return CleanupResult(texts=results, requests=request_count)

    # ------------------------------------------------------------ helpers
    def _build_user_prompt(self, batch: list[str]) -> str:
        # one line per cue keeps the output line-aligned with the batch
        text = "\n".join(batch)
        note = "" if len(batch) == 1 else _BATCH_NOTE.format(count=len(batch))
        return f"Clean the following subtitle line(s):{note}\n\n\n{text}"

    def _system_prompt(self, modes: Sequence[str]) -> str:
        instructions = "\n".join(
            f"- {MODE_INSTRUCTIONS[mode]}" for mode in modes if mode in MODE_INSTRUCTIONS
        )
        return _SYSTEM_PROMPT.format(instructions=instructions)

    def _chat(self, prompt: str, modes: Sequence[str]) -> str:
        payload = self._request(
            _CHAT_PATH,
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": self._system_prompt(modes)},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": 0},
            },
        )
        content = str(payload.get("message", {}).get("content", "")).strip()
        if not content:
            raise CleanupServiceError(502, "Ollama returned an unreadable response.")
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
            raise CleanupServiceError(
                502, "Could not reach Ollama. Check that it is running at the configured OLLAMA_URL."
            ) from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("Ollama returned non-JSON body (%d bytes)", len(raw))
            raise CleanupServiceError(502, "Ollama returned an unreadable response.") from exc

    def _http_error(self, exc: urllib.error.HTTPError) -> CleanupServiceError:
        detail = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
            parsed = json.loads(body)
            detail = str(parsed.get("error", body[:200]))
        except (OSError, ValueError):
            pass
        logger.warning("Ollama HTTP %s: %s", exc.code, detail)
        if exc.code == 404:
            return CleanupServiceError(
                404,
                f"Model '{self._model}' is not installed in Ollama. "
                f"Run 'ollama pull {self._model}' or pick another model.",
            )
        return CleanupServiceError(
            502, "Ollama returned an error while cleaning subtitles. Check the backend logs."
        )


def make_ollama_cleaner(
    settings: Settings | None = None, model: str | None = None
) -> OllamaCleanupClient:
    """Client from settings (always constructible - reachability is only
    known when a request is actually made)."""
    cfg = settings or get_settings()
    return OllamaCleanupClient(
        base_url=cfg.ollama_url,
        model=model or cfg.ollama_cleanup_model,
        timeout_seconds=cfg.ollama_timeout_seconds,
    )
