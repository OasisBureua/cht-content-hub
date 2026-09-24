"""WebVTT → plain text for CPR-13 transcript ingest.

Platform stores raw Zoom WebVTT at ``transcript_s3_key``. Hub strips cue
scaffolding on ingest (Uche 2026-09-22) and persists ``transcript_text``.
"""

from __future__ import annotations

import re

_TIMESTAMP_RE = re.compile(
    r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}[.,]\d{3}"
)
_CUE_NUMBER_RE = re.compile(r"^\d+$")
_NOTE_START_RE = re.compile(r"^NOTE(?:\s|$)")
_STYLE_START_RE = re.compile(r"^STYLE(?:\s|$)")
_REGION_START_RE = re.compile(r"^REGION(?:\s|$)")
_TAG_RE = re.compile(r"</?[^>]+>")


def strip_vtt(raw: str) -> str:
    """Remove WebVTT headers, timings, and cue ids; keep spoken text.

    Blank lines between cues become single newlines. Leading/trailing
    whitespace on the whole document is trimmed. Returns ``""`` for empty
    or header-only input.
    """
    if not raw or not raw.strip():
        return ""

    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    text_lines: list[str] = []
    skipping_block = False

    for line in lines:
        stripped = line.strip()

        if skipping_block:
            if stripped == "":
                skipping_block = False
            continue

        if not stripped:
            continue
        if stripped.upper().startswith("WEBVTT"):
            continue
        if _NOTE_START_RE.match(stripped) or _STYLE_START_RE.match(stripped) or _REGION_START_RE.match(stripped):
            skipping_block = True
            continue
        if _CUE_NUMBER_RE.match(stripped):
            continue
        if _TIMESTAMP_RE.match(stripped):
            continue

        cleaned = _TAG_RE.sub("", stripped).strip()
        if cleaned:
            text_lines.append(cleaned)

    return "\n".join(text_lines)
