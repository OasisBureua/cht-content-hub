"""Phase D: WebVTT cue-stripping unit tests."""

from __future__ import annotations

from pathlib import Path

from services.export_ingest.vtt import strip_vtt

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "platform_export"


def test_strip_sample_fixture_vtt():
    raw = (FIXTURES / "sample_transcript.vtt").read_text(encoding="utf-8")
    text = strip_vtt(raw)
    assert "WEBVTT" not in text
    assert "-->" not in text
    assert "NOTE" not in text
    assert "Dr. Smith: Welcome to today's session." in text
    assert "Thank you for joining us." in text
    assert text == (
        "Dr. Smith: Welcome to today's session.\n"
        "Thank you for joining us."
    )


def test_strip_vtt_empty():
    assert strip_vtt("") == ""
    assert strip_vtt("WEBVTT\n\n") == ""


def test_strip_vtt_removes_inline_tags():
    raw = """WEBVTT

00:00:00.000 --> 00:00:01.000
<v Speaker>Hello <b>world</b>
"""
    assert strip_vtt(raw) == "Hello world"


def test_strip_vtt_skips_style_block():
    raw = """WEBVTT

STYLE
::cue { color: red }

00:00:00.000 --> 00:00:01.000
Spoken line
"""
    assert strip_vtt(raw) == "Spoken line"
