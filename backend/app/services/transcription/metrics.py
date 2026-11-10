"""Transcription accuracy metrics for benchmarking (section 18.3).

- WER for space-separated languages (English etc.)
- CER for unspaced languages (Thai, Japanese, Chinese)
- Timestamp error helpers

All functions are pure and dependency-free so they can be unit-tested and
used by scripts/benchmark.py without loading the AI stack.
"""

from __future__ import annotations

import re


def levenshtein(a: list[str], b: list[str]) -> int:
    """Classic dynamic-programming edit distance over token lists."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, token_a in enumerate(a, start=1):
        current = [i]
        for j, token_b in enumerate(b, start=1):
            cost = 0 if token_a == token_b else 1
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            )
        previous = current
    return previous[-1]


def tokenize_words(text: str) -> list[str]:
    return re.findall(r"\S+", normalize_for_metrics(text))


def tokenize_chars(text: str) -> list[str]:
    """Characters with whitespace removed (suits unspaced languages)."""
    return [ch for ch in normalize_for_metrics(text) if not ch.isspace()]


def normalize_for_metrics(text: str) -> str:
    """Light normalization: strip punctuation/whitespace noise, lowercase."""
    lowered = text.lower()
    # keep letters (incl. Thai), digits and internal spaces
    cleaned = re.sub(r"[^\w\s฀-๿]", "", lowered, flags=re.UNICODE)
    return re.sub(r"\s+", " ", cleaned).strip()


def word_error_rate(reference: str, hypothesis: str) -> float:
    """WER in [0, 1+]; 0.0 for identical (after normalization)."""
    ref = tokenize_words(reference)
    hyp = tokenize_words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return levenshtein(ref, hyp) / len(ref)


def character_error_rate(reference: str, hypothesis: str) -> float:
    """CER in [0, 1+] — the metric of choice for Thai/Japanese/Chinese."""
    ref = tokenize_chars(reference)
    hyp = tokenize_chars(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return levenshtein(ref, hyp) / len(ref)


def mean_timestamp_error_ms(
    reference: list[tuple[float, float]], hypothesis: list[tuple[float, float]]
) -> float:
    """Mean absolute start-time error in ms over paired segments."""
    if not reference or not hypothesis:
        return 0.0
    pairs = min(len(reference), len(hypothesis))
    total = sum(
        abs(reference[i][0] - hypothesis[i][0]) * 1000 for i in range(pairs)
    )
    return total / pairs


def real_time_factor(processing_seconds: float, media_seconds: float) -> float:
    """RTF < 1 means faster than real time."""
    if media_seconds <= 0:
        return 0.0
    return processing_seconds / media_seconds
