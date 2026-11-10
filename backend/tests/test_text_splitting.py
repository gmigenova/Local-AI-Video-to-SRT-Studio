"""Tests for text wrapping / splitting (Thai + English, section 6.1)."""

from __future__ import annotations

import pytest

from app.services.subtitle.text_splitting import (
    contains_thai,
    split_long_token,
    wrap_text,
)


def _all_lines_within(text: str, limit: int) -> bool:
    return all(len(line) <= limit for line in text.split("\n"))


class TestEnglishWrapping:
    def test_short_text_untouched(self):
        assert wrap_text("Hello everyone.", 42, 2) == "Hello everyone."

    def test_wraps_at_spaces_only(self):
        text = " ".join(["word"] * 30)  # 150 chars
        wrapped = wrap_text(text, 42, 2)
        lines = wrapped.split("\n")
        assert len(lines) > 1
        for line in lines:
            assert len(line) <= 42
            assert not line.startswith(" ") and not line.endswith(" ")

    def test_never_splits_words(self):
        text = "internationalization " * 10 + "extraordinary"
        wrapped = wrap_text(text, 42, 2)
        for line in wrapped.split("\n"):
            for word in line.split(" "):
                assert word in {"internationalization", "extraordinary"}

    def test_unbreakable_token_overflows_instead_of_being_cut(self):
        token = "a" * 80
        wrapped = wrap_text(token, 42, 2)
        assert wrapped == token  # kept intact rather than split


class TestThaiSplitting:
    THAI_LONG = "สวัสดีครับวันนี้เราจะมาเรียนรู้เรื่องปัญญาประดิษฐ์และการประมวลผลภาษาธรรมชาติกันครับ"

    def test_contains_thai(self):
        assert contains_thai("สวัสดี")
        assert not contains_thai("hello")
        assert contains_thai("hello สวัสดี")

    @pytest.mark.skipif(
        __import__("importlib.util", fromlist=["find_spec"]).find_spec("pythainlp")
        is not None,
        reason="pythainlp installed: testing the fallback path is not meaningful",
    )
    def test_long_thai_token_hard_split_without_pythainlp(self):
        pieces = split_long_token(self.THAI_LONG, 42)
        assert len(pieces) > 1
        assert all(len(p) <= 42 for p in pieces)
        assert "".join(pieces) == self.THAI_LONG

    def test_wrap_thai_stays_within_limit_without_pythainlp(self):
        wrapped = wrap_text(self.THAI_LONG, 42, 2)
        assert _all_lines_within(wrapped, 42)
        assert "".join(wrapped.split("\n")) == self.THAI_LONG

    def test_wrap_mixed_thai_english(self):
        text = "สวัสดีครับ " + "hello " * 12 + "world"
        wrapped = wrap_text(text, 42, 2)
        assert _all_lines_within(wrapped, 42)


class TestGeneric:
    def test_text_never_dropped(self):
        text = "x" * 300
        wrapped = wrap_text(text, 42, 2)
        assert wrapped.replace("\n", "") == text
