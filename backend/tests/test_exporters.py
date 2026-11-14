"""Tests for timestamp formatting and subtitle exporters (section 12, 18.1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.errors import ExportError
from app.services.subtitle.exporters import (
    ASSExporter,
    ASSStyle,
    JSONExporter,
    SRTExporter,
    TXTExporter,
    VTTExporter,
    escape_ass_text,
    format_timestamp_ass,
    format_timestamp_srt,
    format_timestamp_vtt,
    get_exporter,
    rgb_to_ass_color,
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


class TestASSFormat:
    def test_centisecond_timestamps(self):
        assert format_timestamp_ass(0) == "0:00:00.00"
        assert format_timestamp_ass(1200) == "0:00:01.20"
        assert format_timestamp_ass(3_723_649) == "1:02:03.64"  # 649 ms -> 64 cs

    def test_negative_clamped_to_zero(self):
        assert format_timestamp_ass(-100) == "0:00:00.00"

    def test_rgb_converted_to_opaque_bgr(self):
        assert rgb_to_ass_color("#FFFFFF") == "&H00FFFFFF"
        assert rgb_to_ass_color("FF0000") == "&H000000FF"  # red -> BGR flip
        assert rgb_to_ass_color("00ff00") == "&H0000FF00"  # green, case-insensitive

    def test_invalid_color_rejected(self):
        for bad in ("", "#FFF", "12345", "GGGGGG", "#12345Z"):
            with pytest.raises(ExportError):
                rgb_to_ass_color(bad)

    def test_escape_neutralizes_braces_and_newlines(self):
        assert escape_ass_text("{\\i1}bold{\\i0}") == "(\\i1)bold(\\i0)"
        assert escape_ass_text("line one\nline two") == "line one\\Nline two"
        assert escape_ass_text("  \n  ") == ""


class TestASSExporter:
    def test_header_and_dialogue_shape(self):
        rendered = ASSExporter().render(make_subs())
        assert rendered.startswith("[Script Info]\r\n")
        assert "ScriptType: v4.00+" in rendered
        assert "[V4+ Styles]" in rendered
        assert "[Events]" in rendered
        assert "Style: Default,Arial,48," in rendered
        assert (
            "Dialogue: 0,0:00:01.20,0:00:03.50,Default,,0,0,0,,Hello everyone.\r\n" in rendered
        )
        assert (
            "Dialogue: 0,0:00:03.60,0:00:06.20,Default,,0,0,0,,"
            "Welcome to this tutorial.\r\n" in rendered
        )

    def test_style_overrides_lands_in_the_style_line(self):
        style = ASSStyle(
            font_name="Leelawadee UI",
            font_size=64,
            primary_color="&H0000FFFF",
            outline=3,
            alignment=8,
            margin_v=60,
            play_res_x=3840,
            play_res_y=2160,
        )
        rendered = ASSExporter(style).render(make_subs())
        assert "Style: Default,Leelawadee UI,64,&H0000FFFF" in rendered
        assert "PlayResX: 3840" in rendered
        assert "PlayResY: 2160" in rendered
        # Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding tail
        assert ",3,0,8,10,10,60,1" in rendered

    def test_commas_and_braces_in_font_name_sanitised(self):
        style = ASSStyle(font_name="My, Fo{nt}")
        rendered = ASSExporter(style).render(make_subs())
        assert "Style: Default,My Font," in rendered

    def test_braces_in_text_neutralised_and_skips_empty(self):
        subs = [
            Subtitle(index=1, start_ms=0, end_ms=900, text="{\\i1}hi{\\i0}", original_text="x"),
            Subtitle(index=2, start_ms=1000, end_ms=1900, text="  ", original_text=""),
        ]
        rendered = ASSExporter().render(subs)
        assert "Dialogue: 0,0:00:00.00,0:00:00.90,Default,,0,0,0,,(\\i1)hi(\\i0)\r\n" in rendered
        assert len([line for line in rendered.splitlines() if line.startswith("Dialogue")]) == 1

    def test_thai_text_round_trips(self):
        subs = [
            Subtitle(index=1, start_ms=0, end_ms=2000, text="สวัสดีครับ", original_text="x")
        ]
        rendered = ASSExporter().render(subs)
        assert "สวัสดีครับ" in rendered

    def test_registered_in_registry_and_export_helper(self):
        assert get_exporter("ass").format_name == "ass"
        from app.services.subtitle.exporters import export_subtitles

        target = Path(__file__).parent / "_tmp_test.ass"
        try:
            export_subtitles(make_subs(), target, "ass")
            content = target.read_text(encoding="utf-8")
            assert content.startswith("[Script Info]")
        finally:
            target.unlink(missing_ok=True)


class TestExporterRegistry:
    def test_get_exporter_case_insensitive(self):
        assert get_exporter("SRT").format_name == "srt"

    def test_unknown_format_raises(self):
        with pytest.raises(ExportError):
            get_exporter("docx")
