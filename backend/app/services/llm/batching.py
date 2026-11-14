"""Shared line-batching helpers for Ollama-backed text operations.

Both the TranslateGemma translation client
(``app.services.translation.ollama_translate``) and the LLM cleanup client
(``app.services.llm.cleanup``) send cues to a local Ollama server in
line-aligned batches: one cue per line, the reply must come back with the
same number of lines, and a line-count mismatch falls back to per-cue
requests.  Those mechanics live here once so the two clients cannot drift.
"""

from __future__ import annotations

import re

#: Conservative per-request caps - LLM latency grows with batch size.
MAX_CUES_PER_REQUEST = 25
MAX_CHARS_PER_REQUEST = 3000

#: Model-added enumeration prefixes ("1. text", "2) text", "Line 3 - text")
#: that sometimes appear in batch replies despite the prompt.
ENUMERATION = re.compile(r"^(?:line\s*)?(?P<n>\d+)[.):]?\s+", re.IGNORECASE)


def split_lines(content: str) -> list[str]:
    """Split a model reply into trimmed, edge-blank-free lines."""
    lines = [line.strip() for line in content.strip().split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return lines


def strip_enumeration_prefixes(lines: list[str]) -> list[str]:
    """Drop model-added enumeration prefixes ("1. text", "2) text").

    A prefix is removed only when its number matches the line's position in
    the reply AND at least half the lines carry such a matching number, so
    genuine text that happens to start with digits (countdowns, amounts,
    lyric numbering) survives.
    """
    if len(lines) < 2:
        return lines
    matches = [ENUMERATION.match(line) for line in lines]
    aligned = [
        match is not None and match.group("n") == str(position)
        for position, match in enumerate(matches, start=1)
    ]
    if sum(aligned) * 2 < len(lines):
        return lines
    return [
        line[match.end() :] if ok and match is not None else line
        for line, match, ok in zip(lines, matches, aligned, strict=True)
    ]


def build_batches(
    texts: list[str],
    max_cues: int = MAX_CUES_PER_REQUEST,
    max_chars: int = MAX_CHARS_PER_REQUEST,
) -> list[tuple[list[int], list[str]]]:
    """Split non-empty (whitespace-collapsed) cues into request-sized
    ``(positions, batch)`` pairs.  Empty cues are skipped - callers pass
    them through untouched."""
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
            continue
        if len(batch) >= max_cues or (chars + len(stripped) > max_chars and batch):
            flush()
        positions.append(i)
        batch.append(stripped)
        chars += len(stripped)
    flush()
    return batches
