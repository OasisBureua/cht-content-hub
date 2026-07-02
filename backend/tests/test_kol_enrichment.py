"""Tests for services.kol_enrichment — brief markdown parsing."""

from __future__ import annotations

from services.kol_enrichment import _parse_brief_sections


def test_parse_all_three_sections():
    """Standard MediaHub brief with all three headings populates all three fields."""
    md = (
        "## Who they are\n"
        "Jason Mouabbi is a hematology and oncology specialist at MD Anderson.\n"
        "\n"
        "## What they focus on\n"
        "Clinical focus centers on breast cancer management.\n"
        "\n"
        "## CHM context\n"
        "Jason Mouabbi has no recorded engagement with CHM."
    )

    result = _parse_brief_sections(md)

    assert result.whoTheyAre == (
        "Jason Mouabbi is a hematology and oncology specialist at MD Anderson."
    )
    assert result.focus == "Clinical focus centers on breast cancer management."
    assert result.chmContext == "Jason Mouabbi has no recorded engagement with CHM."


def test_parse_missing_middle_section():
    """A brief without one heading leaves that field as None; others populate."""
    md = (
        "## Who they are\n"
        "A prolific researcher.\n"
        "\n"
        "## CHM context\n"
        "Has attended three CHM webinars."
    )

    result = _parse_brief_sections(md)

    assert result.whoTheyAre == "A prolific researcher."
    assert result.focus is None
    assert result.chmContext == "Has attended three CHM webinars."


def test_parse_multiparagraph_section_preserves_line_breaks():
    """Multi-paragraph section content preserves internal line breaks."""
    md = (
        "## Who they are\n"
        "Line one of the bio.\n"
        "\n"
        "Line three after a blank line.\n"
        "\n"
        "## What they focus on\n"
        "Focus content."
    )

    result = _parse_brief_sections(md)

    assert result.whoTheyAre == (
        "Line one of the bio.\n\nLine three after a blank line."
    )
    assert result.focus == "Focus content."


def test_parse_no_recognized_headings_returns_all_none():
    """A brief with no recognized headings produces an all-None result."""
    md = "Just some free-form text without any markdown headings at all."

    result = _parse_brief_sections(md)

    assert result.whoTheyAre is None
    assert result.focus is None
    assert result.chmContext is None


def test_parse_ignores_unknown_headings():
    """Sections under unrecognized headings are dropped; known sections still populate."""
    md = (
        "## Who they are\n"
        "Bio content.\n"
        "\n"
        "## Random other heading\n"
        "This should not appear anywhere.\n"
        "\n"
        "## CHM context\n"
        "CHM engagement content."
    )

    result = _parse_brief_sections(md)

    assert result.whoTheyAre == "Bio content."
    assert result.focus is None
    assert result.chmContext == "CHM engagement content."


def test_parse_heading_case_insensitive():
    """Heading matching is case-insensitive to tolerate MediaHub casing drift."""
    md = "## WHO THEY ARE\nContent A.\n\n## What They Focus On\nContent B."

    result = _parse_brief_sections(md)

    assert result.whoTheyAre == "Content A."
    assert result.focus == "Content B."


def test_parse_whitespace_only_section_becomes_none():
    """A recognized heading followed by only whitespace produces None, not empty string."""
    md = "## Who they are\n\n\n## CHM context\nActual content."

    result = _parse_brief_sections(md)

    assert result.whoTheyAre is None
    assert result.chmContext == "Actual content."


def test_parse_content_before_first_heading_is_ignored():
    """Content that appears before any recognized heading is dropped."""
    md = (
        "This preamble should not appear anywhere in the output.\n"
        "\n"
        "## Who they are\n"
        "Real content."
    )

    result = _parse_brief_sections(md)

    assert result.whoTheyAre == "Real content."
    assert result.focus is None
    assert result.chmContext is None
