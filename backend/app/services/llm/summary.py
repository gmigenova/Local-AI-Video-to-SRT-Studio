"""LLM video summary via a local Ollama server (stdlib only).

Summarises a job's *saved* subtitles into a short summary plus key points
with ``[mm:ss]`` timestamps.  Long transcripts are processed map-reduce
style under the same per-request char cap as the cleanup / translate
batching, so every request stays well inside Ollama's default context
window.  All failures raise :class:`SummaryServiceError` with an HTTP
status + clean, user-facing message (§16).
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.core.config import Settings, get_settings
from app.services.llm.batching import MAX_CHARS_PER_REQUEST

logger = logging.getLogger(__name__)

_CHAT_PATH = "/api/chat"

#: Output languages the prompts are written for (matches the app's
#: Thai/English focus); other source languages summarise in English.
_LANGUAGE_NAMES: dict[str, str] = {"th": "Thai", "en": "English"}

_TIMESTAMP = re.compile(r"^\[(?:(\d+):)?(\d{1,3}):(\d{2})\]\s*")
_BULLET = re.compile(r"^[-*•]\s+")

_FULL_SYSTEM_PROMPT = (
    "You are a video summariser. You are given a video's subtitles as "
    "timestamped cue lines ([mm:ss] text, in order). Produce exactly this "
    "format:\n"
    "SUMMARY:\n"
    "<2-4 sentences capturing what the video is about>\n"
    "\n"
    "KEY POINTS:\n"
    "- [mm:ss] <one concise point>\n"
    "- [mm:ss] <one concise point>\n"
    "Rules:\n"
    "- Write in {language}.\n"
    "- 5-10 key points max, ordered by timestamp; each [mm:ss] must be the "
    "timestamp of the cue the point comes from.\n"
    "- Output nothing else - no preamble, no markdown headings besides the "
    "two section labels above."
)

_MAP_SYSTEM_PROMPT = (
    "You are a video summariser. You are given a PORTION of a video's "
    "subtitles as timestamped cue lines ([mm:ss] text, in order). List the "
    "3-6 most important points of this portion.\n"
    "Rules:\n"
    "- Write in {language}.\n"
    "- One point per line, formatted exactly as: - [mm:ss] <point>\n"
    "- Each [mm:ss] must be the timestamp of the cue the point comes from.\n"
    "- Output nothing else - no summary, no preamble."
)

_REDUCE_SYSTEM_PROMPT = (
    "You are a video summariser. You are given key points from a long "
    "video, each as '- [mm:ss] <point>' lines from different portions of "
    "it. Produce exactly this format:\n"
    "SUMMARY:\n"
    "<2-4 sentences capturing what the video is about>\n"
    "\n"
    "KEY POINTS:\n"
    "- [mm:ss] <one concise point>\n"
    "Rules:\n"
    "- Write in {language}.\n"
    "- Consolidate the points: drop duplicates and minor ones, keep 5-10 "
    "of the most important, ordered by timestamp. Keep each point's "
    "original timestamp.\n"
    "- Output nothing else - no preamble."
)


class SummaryServiceError(Exception):
    """Raised with an HTTP status + clean user-facing message."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass
class SummaryKeyPoint:
    """One key point, anchored to the cue it came from (if parseable)."""

    time_ms: int | None
    text: str


@dataclass
class SummaryResult:
    summary: str
    key_points: list[SummaryKeyPoint] = field(default_factory=list)
    requests: int = 0


def _mm_ss(ms: int) -> str:
    total_seconds = ms // 1000
    return f"{total_seconds // 60:02d}:{total_seconds % 60:02d}"


def _format_cues(cues: Sequence[tuple[int, str]]) -> list[str]:
    """One '[mm:ss] collapsed-text' line per cue (whitespace collapsed like
    the batching helpers, so multi-line cue text stays one line)."""
    return [
        f"[{_mm_ss(start)}] {' '.join(text.split())}"
        for start, text in cues
        if text.strip()
    ]


def _chunk_lines(lines: list[str], max_chars: int = MAX_CHARS_PER_REQUEST) -> list[list[str]]:
    """Group formatted cue lines into request-sized chunks."""
    chunks: list[list[str]] = []
    current: list[str] = []
    chars = 0
    for line in lines:
        if current and chars + len(line) > max_chars:
            chunks.append(current)
            current, chars = [], 0
        current.append(line)
        chars += len(line) + 1
    if current:
        chunks.append(current)
    return chunks


def _parse_stamp(token: str) -> int | None:
    """'[mm:ss]' or '[h:mm:ss]' -> milliseconds (None when malformed)."""
    match = _TIMESTAMP.match(token)
    if match is None:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    return ((hours * 60 + minutes) * 60 + seconds) * 1000


def parse_summary_reply(content: str) -> tuple[str, list[SummaryKeyPoint]]:
    """Lenient parser for the SUMMARY/KEY POINTS contract.

    Missing heading -> the whole reply becomes the summary with no key
    points; unparseable point lines keep their text with ``time_ms=None``.
    Never raises - a half-obedient model degrades gracefully.
    """
    text = content.strip()
    # headings arrive in various decorations: "KEY POINTS:", "## Key Points",
    # "**Key Points:**" - tolerate them all
    parts = re.split(
        r"(?im)^[ \t]*[#*_]*[ \t]*key points[ \t]*[:#*_]*[ \t]*$", text, maxsplit=1
    )
    if len(parts) == 2:
        summary_part, points_part = parts
    else:
        summary_part, points_part = text, ""

    summary = re.sub(
        r"(?im)^[ \t]*[#*_]*[ \t]*summary[ \t]*[:#*_]*[ \t]*", "", summary_part
    ).strip()

    points: list[SummaryKeyPoint] = []
    for raw_line in points_part.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = _BULLET.sub("", line, count=1)
        stamp = _TIMESTAMP.match(line)
        if stamp is not None:
            time_ms = _parse_stamp(line)
            body = line[stamp.end() :].strip()
        else:
            time_ms, body = None, line
        if body:
            points.append(SummaryKeyPoint(time_ms=time_ms, text=body))
    return summary, points


def _points_to_lines(points: list[SummaryKeyPoint]) -> list[str]:
    lines = []
    for point in points:
        stamp = f"[{_mm_ss(point.time_ms)}] " if point.time_ms is not None else ""
        lines.append(f"- {stamp}{point.text}")
    return lines


class OllamaSummaryClient:
    """Video summary from saved subtitles via a local Ollama server."""

    def __init__(self, base_url: str, model: str, timeout_seconds: float = 300.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds

    @property
    def model_name(self) -> str:
        return self._model

    # ---------------------------------------------------------------- api
    def summarize(self, cues: Sequence[tuple[int, str]], language: str) -> SummaryResult:
        """Summarise ``(start_ms, text)`` cues into summary + key points."""
        language_name = _LANGUAGE_NAMES.get(language, "English")
        lines = _format_cues(cues)
        if not lines:
            raise SummaryServiceError(400, "There is no subtitle text to summarise.")

        chunks = _chunk_lines(lines)
        requests = 0

        if len(chunks) <= 1:
            content = self._chat(
                self._fill(_FULL_SYSTEM_PROMPT, language_name),
                "Summarise this video:\n\n" + "\n".join(lines),
            )
            requests += 1
            summary, points = parse_summary_reply(content)
            return SummaryResult(summary=summary, key_points=points, requests=requests)

        # map: one partial key-point list per chunk
        partials: list[list[SummaryKeyPoint]] = []
        for chunk in chunks:
            content = self._chat(
                self._fill(_MAP_SYSTEM_PROMPT, language_name),
                "Key points of this portion:\n\n" + "\n".join(chunk),
            )
            requests += 1
            _, points = parse_summary_reply("KEY POINTS:\n" + content)
            partials.append(points)

        # reduce in waves until everything fits one request, then finalise
        while True:
            flat = [point for partial in partials for point in partial]
            payload_lines = _points_to_lines(flat)
            if sum(len(line) + 1 for line in payload_lines) <= MAX_CHARS_PER_REQUEST:
                content = self._chat(
                    self._fill(_REDUCE_SYSTEM_PROMPT, language_name),
                    "Key points from the whole video:\n\n" + "\n".join(payload_lines),
                )
                requests += 1
                summary, points = parse_summary_reply(content)
                return SummaryResult(summary=summary, key_points=points, requests=requests)

            merged: list[list[SummaryKeyPoint]] = []
            for wave_lines in _chunk_lines(payload_lines):
                content = self._chat(
                    self._fill(_REDUCE_SYSTEM_PROMPT, language_name),
                    "Key points from the whole video:\n\n" + "\n".join(wave_lines),
                )
                requests += 1
                _, points = parse_summary_reply("KEY POINTS:\n" + content)
                merged.append(points)
            partials = merged

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _fill(prompt: str, language_name: str) -> str:
        return prompt.format(language=language_name)

    def _chat(self, system: str, prompt: str) -> str:
        payload = self._request(
            _CHAT_PATH,
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": 0},
            },
        )
        content = str(payload.get("message", {}).get("content", "")).strip()
        if not content:
            raise SummaryServiceError(502, "Ollama returned an unreadable response.")
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
            raise SummaryServiceError(
                502, "Could not reach Ollama. Check that it is running at the configured OLLAMA_URL."
            ) from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("Ollama returned non-JSON body (%d bytes)", len(raw))
            raise SummaryServiceError(502, "Ollama returned an unreadable response.") from exc

    def _http_error(self, exc: urllib.error.HTTPError) -> SummaryServiceError:
        detail = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
            parsed = json.loads(body)
            detail = str(parsed.get("error", body[:200]))
        except (OSError, ValueError):
            pass
        logger.warning("Ollama HTTP %s: %s", exc.code, detail)
        if exc.code == 404:
            return SummaryServiceError(
                404,
                f"Model '{self._model}' is not installed in Ollama. "
                f"Run 'ollama pull {self._model}' or pick another model.",
            )
        return SummaryServiceError(
            502, "Ollama returned an error while summarising. Check the backend logs."
        )


def make_ollama_summarizer(
    settings: Settings | None = None, model: str | None = None
) -> OllamaSummaryClient:
    """Client from settings (always constructible - reachability is only
    known when a request is actually made). Model resolution: explicit
    argument -> OLLAMA_SUMMARY_MODEL -> OLLAMA_CLEANUP_MODEL."""
    cfg = settings or get_settings()
    return OllamaSummaryClient(
        base_url=cfg.ollama_url,
        model=model or cfg.ollama_summary_model or cfg.ollama_cleanup_model,
        timeout_seconds=cfg.ollama_timeout_seconds,
    )
