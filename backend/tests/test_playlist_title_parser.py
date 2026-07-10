"""Unit tests for playlist_title_parser.

Verifies the four real-world CHM playlist title patterns documented in
the parser module (A: full names ampersand-joined, B: surname-only chain
after Drs., C: full names in Drs. chain, D: doctors at end after topic
prefix). Also verifies typo corrections apply and canonical output ordering.
"""

from __future__ import annotations

from services.playlist_title_parser import (
    doctor_tags_from_playlist_title,
    extract_doctors_from_playlist_title,
)


# ─────────────────────────────────────────────────────────────────────────────
# Pattern A — "Dr. <First> <Last> & Dr. <First> <Last>"
# ─────────────────────────────────────────────────────────────────────────────


def test_pattern_a_two_doctors_ampersand():
    assert extract_doctors_from_playlist_title(
        "Dr. Mark Pegram & Dr. Neil Iyengar"
    ) == ["Pegram", "Iyengar"]


def test_pattern_a_end_of_title():
    assert extract_doctors_from_playlist_title(
        "Is HER2+ MBC Curable? - Dr. Gregory Vidal & Dr. Nusayba Bagegni"
    ) == ["Vidal", "Bagegni"]


# ─────────────────────────────────────────────────────────────────────────────
# Pattern B — "Drs. <surname>, <surname> & <surname> <verb> ..."
# ─────────────────────────────────────────────────────────────────────────────


def test_pattern_b_surname_chain_with_apostrophe():
    result = extract_doctors_from_playlist_title(
        "Drs. Mouabbi, O'Shaughnessy & Rimawi Rethink First-Line HER2+ MBC"
    )
    assert result == ["Mouabbi", "O'Shaughnessy", "Rimawi"]


# ─────────────────────────────────────────────────────────────────────────────
# Pattern C — "... with Drs. <Full Name>, <Full Name> & <Full Name>"
# ─────────────────────────────────────────────────────────────────────────────


def test_pattern_c_full_names_with_drs_prefix():
    result = extract_doctors_from_playlist_title(
        "Cleopatra, DESTINY-Breast09 & What Comes Next with Drs. Bill Gradishar, "
        "Tarah Ballinger, & Megan Kruse"
    )
    assert result == ["Gradishar", "Ballinger", "Kruse"]


# ─────────────────────────────────────────────────────────────────────────────
# Typo corrections
# ─────────────────────────────────────────────────────────────────────────────


def test_typo_correction_shaughnessey_to_shaughnessy():
    """The parser should normalize 'O'Shaughnessey' → 'O'Shaughnessy'."""
    # Use a Drs. chain form since it stops cleanly at the "Rethink"
    # end-of-chain word — the "Dr. <Name>" form is greedy and can extend
    # through following capitalized-hyphenated tokens like "First-Line".
    result = extract_doctors_from_playlist_title(
        "Drs. O'Shaughnessey & Rimawi Rethink First-Line"
    )
    assert "O'Shaughnessy" in result
    assert "O'Shaughnessey" not in result


def test_hyphenated_surname_preserved():
    """Hyphenated surnames like Garrido-Castro should survive parsing."""
    result = extract_doctors_from_playlist_title(
        "Dr. Ana Garrido-Castro on HER2+ Treatment"
    )
    assert result == ["Garrido-Castro"]


# ─────────────────────────────────────────────────────────────────────────────
# Deduplication
# ─────────────────────────────────────────────────────────────────────────────


def test_duplicate_doctor_deduplicated():
    """If the same doctor appears twice, they are emitted once."""
    # Two "Dr." prefixes both parse to Pegram; canonical set is deduped.
    result = extract_doctors_from_playlist_title(
        "Dr. Mark Pegram & Dr. Mark Pegram"
    )
    assert result == ["Pegram"]


# ─────────────────────────────────────────────────────────────────────────────
# Convenience wrapper
# ─────────────────────────────────────────────────────────────────────────────


def test_doctor_tags_wrapper_prefixes_correctly():
    result = doctor_tags_from_playlist_title(
        "Dr. Mark Pegram & Dr. Neil Iyengar"
    )
    assert result == ["doctor:Pegram", "doctor:Iyengar"]


# ─────────────────────────────────────────────────────────────────────────────
# Empty / edge cases
# ─────────────────────────────────────────────────────────────────────────────


def test_empty_title_returns_empty_list():
    assert extract_doctors_from_playlist_title("") == []


def test_title_with_no_doctors_returns_empty_list():
    assert extract_doctors_from_playlist_title(
        "The Future of HER2+ Metastatic Breast Cancer"
    ) == []


def test_none_title_handled_gracefully():
    # The parser accepts None and returns an empty list rather than raising.
    assert extract_doctors_from_playlist_title(None) == []  # type: ignore[arg-type]
