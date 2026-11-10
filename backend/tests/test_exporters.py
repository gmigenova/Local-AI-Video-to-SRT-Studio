"""Tests for timestamp formatting and subtitle exporters (section 12, 18.1)."""

from __future__ import annotations

import json

import pytest

from app.core.errors import ExportError
from app.services.subtitle.exporters import (
    JSONExporter,
    SRTExporter,
    TXTExporter,
    VTTExporter,
    format_timestamp_srt,
    format_timestamp_vtt,
    get_exporter,
)
from app.services.subtitle.models import Subtitle


def make_subs() -> list[Subtitle]:
    return [
        Subtitle(index=1, start_ms=1200, end_ms=3500, text="Hello everyone.", original_text="Hello everyone."),
        Subtitle(index=2, start_ms=3600, end_ms=6200, text="Welcome to this tutorial.", original_text="Welcome to this tutorial."),
    ]


class TestTimestamps:
    def test_zero(self):
        assert format_timestamp_srt(0) == "00:00:00,000"

    def test_spec_example(self):
        assert format_timestamp_srt(1200) == "00:00:01,200"
        assert format_timestamp_srt(3500) == "00:00:03,500"

    def test_hours_minutes_seconds_millis(self):
        assert format_timestamp_srt(3_723_456) == "01:02:03,456"

    def test_negative_clamped_to_zero(self):
        assert format_timestamp_srt(-500) == "00:00:00,000"

    def test_vtt_uses_dot(self):
        assert format_timestamp_vtt(1200) == "00:00:01.200"
        assert format_timestamp_vtt(3_723_456) == "01:02:03.456"


class TestSRTExporter:
    def test_renders_spec_example(self):
        rendered = SRTExporter().render(make_subs())
        expected = (
            "1\r\n"
            "00:00:01,200 --> 00:00:03,500\r\n"
            "Hello everyone.\r\n"
            "\r\n"
            "2\r\n"
            "00:00:03,600 --> 00:00:06,200\r\n"
            "Welcome to this tutorial.\r\n"
        )
        assert rendered == expected

    def test_uses_crlf_and_blank_line_between_entries(self):
        rendered = SRTExporter().render(make_subs())
        assert "\r\n\r\n" in rendered
        assert "\r\n" in rendered

    def test_renumbers_gaps(self):
        subs = [
            Subtitle(index=7, start_ms=0, end_ms=900, text="A", original_text="A"),
            Subtitle(index=9, start_ms=1000, end_ms=1900, text="B", original_text="B"),
        ]
        rendered = SRTExporter().render(subs)
        assert rendered.startswith("1\r\n")
        assert "\r\n\r\n2\r\n" in rendered

    def test_skips_empty_text(self):
        subs = [Subtitle(index=1, start_ms=0, end_ms=900, text="  ", original_text="")]
        assert SRTExporter().render(subs) == ""

    def test_bom_written_when_requested(self, tmp_path):
        target = tmp_path / "out.srt"
        SRTExporter().export(make_subs(), target, utf8_bom=True)
        assert target.read_bytes().startswith(b"\xef\xbb\xbf")

    def test_no_bom_by_default(self, tmp_path):
        target = tmp_path / "out.srt"
        SRTExporter().export(make_subs(), target)
        assert not target.read_bytes().startswith(b"\xef\xbb\xbf")

    def test_multiline_text_preserved(self):
        subs = [
            Subtitle(index=1, start_ms=0, end_ms=2000, text="line one\nline two", original_text="x")
        ]
        rendered = SRTExporter().render(subs)
        assert "line one\r\nline two" in rendered


class TestOtherExporters:
    def test_vtt_header_and_cues(self):
        rendered = VTTExporter().render(make_subs())
        assert rendered.startswith("WEBVTT\n\n")
        assert "00:00:01.200 --> 00:00:03.500" in rendered
        assert "," not in rendered.split("\n")[2]

    def test_txt_flattens_lines(self):
        subs = [
            Subtitle(index=1, start_ms=0, end_ms=2000, text="line one\nline two", original_text="x")
        ]
        rendered = TXTExporter().render(subs)
        assert "line one line two" in rendered

    def test_json_round_trip(self):
        rendered = JSONExporter().render(make_subs())
        payload = json.loads(rendered)
        assert payload["subtitles"][0]["start_ms"] == 1200
        assert payload["subtitles"][1]["text"] == "Welcome to this tutorial."
        assert payload["subtitles"][0]["is_edited"] is False

    def test_thai_text_not_escaped_in_json(self):
        subs = [
            Subtitle(index=1, start_ms=0, end_ms=2000, text="สวัสดีครับ", original_text="สวัสดีครับ")
        ]
        assert "สวัสดีครับ" in JSONExporter().render(subs)


class TestExporterRegistry:
    def test_get_exporter_case_insensitive(self):
        assert get_exporter("SRT").format_name == "srt"

    def test_unknown_format_raises(self):
        with pytest.raises(ExportError):
            get_exporter("docx")
