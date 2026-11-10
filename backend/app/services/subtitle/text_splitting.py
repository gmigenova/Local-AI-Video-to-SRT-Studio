"""Text line-wrapping for subtitles (section 6.1).

Rules:
- Lines are broken at spaces for space-separated languages (English etc.);
  words are never split.
- For Thai, tokens without spaces may exceed the line length.  When
  `pythainlp` is installed (requirements-thai.txt) such tokens are split at
  Thai word boundaries; without it, tokens are hard-split at the character
  limit as a last resort (documented limitation, never a crash).
- A single unbreakable token in a space language (URL, long word) is allowed
  to overflow its line rather than being cut; callers surface a warning.
- Text is never dropped.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_THAI_FIRST = "฀"
_THAI_LAST = "๿"


def contains_thai(text: str) -> bool:
    return any(_THAI_FIRST <= ch <= _THAI_LAST for ch in text)


def _segment_thai(text: str) -> list[str] | None:
    """Thai word segmentation via pythainlp, or ``None`` when unavailable."""
    try:
        from pythainlp.tokenize import word_tokenize
    except ImportError:
        return None
    try:
        return [t for t in word_tokenize(text, engine="newmm") if t.strip()]
    except Exception:  # pragma: no cover - tokenizer bugs must not break export
        logger.warning("pythainlp tokenization failed; falling back to hard split.")
        return None


def _hard_chop(token: str, max_chars: int) -> list[str]:
    return [token[i : i + max_chars] for i in range(0, len(token), max_chars)]


def split_long_token(token: str, max_chars: int) -> list[str]:
    """Split a token longer than ``max_chars`` into pieces that fit a line."""
    if contains_thai(token):
        subwords = _segment_thai(token)
        if subwords:
            pieces: list[str] = []
            current = ""
            for subword in subwords:
                if len(subword) > max_chars:  # pathological single subword
                    if current:
                        pieces.append(current)
                        current = ""
                    pieces.extend(_hard_chop(subword, max_chars))
                    continue
                if not current:
                    current = subword
                elif len(current) + len(subword) <= max_chars:
                    current += subword  # Thai words join without spaces
                else:
                    pieces.append(current)
                    current = subword
            if current:
                pieces.append(current)
            return pieces
        logger.debug(
            "pythainlp not installed; hard-splitting a long Thai token at character "
            "boundaries. Install requirements-thai.txt for word-boundary splitting."
        )
        return _hard_chop(token, max_chars)
    # Space language: keep unbreakable tokens intact (may overflow the line).
    return [token]


def wrap_text(text: str, max_chars_per_line: int = 42, max_lines: int = 2) -> str:
    """Wrap ``text`` into lines of at most ``max_chars_per_line`` characters.

    May return more than ``max_lines`` lines when the text cannot be broken
    further - the caller is responsible for warning.  Text is never dropped.
    """
    if len(text) <= max_chars_per_line:
        return text

    # units: (unit, join_without_space_to_previous)
    units: list[tuple[str, bool]] = []
    for token in text.split(" "):
        if len(token) <= max_chars_per_line:
            units.append((token, False))
        else:
            for i, piece in enumerate(split_long_token(token, max_chars_per_line)):
                units.append((piece, i > 0))

    lines: list[str] = []
    current = ""
    for unit, join_tight in units:
        if not current:
            current = unit
            continue
        sep = "" if join_tight else " "
        if len(current) + len(sep) + len(unit) <= max_chars_per_line:
            current += sep + unit
        else:
            lines.append(current)
            current = unit
    if current:
        lines.append(current)
    return "\n".join(lines)
