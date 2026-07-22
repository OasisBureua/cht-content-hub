"""Unit tests for playlist_doctor_tagger — pure logic (no YouTube/DB).

Verifies the tag-merge semantics (replace vs. union), doctor-only filtering,
canonical rendering of Shoot.doctors[], and disagreement detection. These
tests do not exercise the async DB loop — that runs against a live DB.
"""

from __future__ import annotations

from jobs.playlist_doctor_tagger_core import (
    _canonical_doctors_field,
    _shoot_doctors_disagree,
    _strip_doctor_tags,
    _surname_from_doctor_field,
    merge_doctor_tags,
    union_doctor_tags,
)


# ─────────────────────────────────────────────────────────────────────────────
# _strip_doctor_tags
# ─────────────────────────────────────────────────────────────────────────────


def test_strip_doctor_tags_removes_doctor_only():
    result = _strip_doctor_tags(["doctor:Pegram", "drug:T-DXd", "doctor:Iyengar"])
    assert result == ["drug:T-DXd"]


def test_strip_doctor_tags_empty_input():
    assert _strip_doctor_tags(None) == []
    assert _strip_doctor_tags([]) == []


# ─────────────────────────────────────────────────────────────────────────────
# merge_doctor_tags (replace semantics)
# ─────────────────────────────────────────────────────────────────────────────


def test_merge_replaces_all_doctor_tags():
    """Replace mode: existing doctor tags are swapped for canonical set."""
    existing = ["doctor:WrongName", "drug:T-DXd", "doctor:AnotherWrong"]
    canonical = ["doctor:Pegram", "doctor:Iyengar"]
    result = merge_doctor_tags(existing, canonical)
    assert "drug:T-DXd" in result
    assert "doctor:Pegram" in result
    assert "doctor:Iyengar" in result
    assert "doctor:WrongName" not in result
    assert "doctor:AnotherWrong" not in result


def test_merge_preserves_non_doctor_tag_order():
    existing = ["drug:T-DXd", "biomarker:HER2+", "doctor:Old"]
    canonical = ["doctor:New"]
    result = merge_doctor_tags(existing, canonical)
    # Non-doctor tags come first, in original order
    assert result[:2] == ["drug:T-DXd", "biomarker:HER2+"]
    assert result[2] == "doctor:New"


def test_merge_idempotent_when_already_correct():
    """If existing doctor set matches canonical exactly, return existing unchanged."""
    existing = ["doctor:Pegram", "doctor:Iyengar", "drug:T-DXd"]
    canonical = ["doctor:Iyengar", "doctor:Pegram"]  # set-equal, different order
    result = merge_doctor_tags(existing, canonical)
    assert result == existing  # unchanged


def test_merge_dedupes_output():
    existing = ["drug:T-DXd", "drug:T-DXd"]  # duplicated
    canonical = ["doctor:Pegram", "doctor:Pegram"]
    result = merge_doctor_tags(existing, canonical)
    assert result.count("drug:T-DXd") == 1
    assert result.count("doctor:Pegram") == 1


# ─────────────────────────────────────────────────────────────────────────────
# union_doctor_tags (additive semantics)
# ─────────────────────────────────────────────────────────────────────────────


def test_union_adds_missing_only():
    existing = ["doctor:Pegram", "drug:T-DXd"]
    canonical = ["doctor:Pegram", "doctor:Iyengar"]
    result = union_doctor_tags(existing, canonical)
    assert "doctor:Pegram" in result
    assert "doctor:Iyengar" in result
    assert "drug:T-DXd" in result


def test_union_preserves_user_curated_extras():
    """Union NEVER removes existing doctor tags, even if not in canonical."""
    existing = ["doctor:HandCurated", "drug:T-DXd"]
    canonical = ["doctor:FromPlaylist"]
    result = union_doctor_tags(existing, canonical)
    assert "doctor:HandCurated" in result  # preserved
    assert "doctor:FromPlaylist" in result  # added


def test_union_no_op_when_all_present():
    existing = ["doctor:Pegram", "doctor:Iyengar"]
    canonical = ["doctor:Pegram"]
    result = union_doctor_tags(existing, canonical)
    assert result == existing  # no changes


# ─────────────────────────────────────────────────────────────────────────────
# _canonical_doctors_field
# ─────────────────────────────────────────────────────────────────────────────


def test_canonical_doctors_field_prefixes_dr():
    assert _canonical_doctors_field(["Pegram", "Iyengar"]) == [
        "Dr. Pegram",
        "Dr. Iyengar",
    ]


# ─────────────────────────────────────────────────────────────────────────────
# _surname_from_doctor_field
# ─────────────────────────────────────────────────────────────────────────────


def test_surname_from_dr_prefix():
    assert _surname_from_doctor_field("Dr. Joyce O'Shaughnessy") == "O'Shaughnessy"


def test_surname_from_bare_surname():
    assert _surname_from_doctor_field("Dr. Pegram") == "Pegram"


def test_surname_from_drs_prefix():
    assert _surname_from_doctor_field("Drs. Mouabbi") == "Mouabbi"


def test_surname_applies_typo_correction():
    assert _surname_from_doctor_field("Dr. Kree") == "Krie"


def test_surname_from_empty_returns_none():
    assert _surname_from_doctor_field("") is None
    assert _surname_from_doctor_field(None) is None  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────────────
# _shoot_doctors_disagree
# ─────────────────────────────────────────────────────────────────────────────


def test_disagree_true_when_shoot_has_wrong_names():
    assert _shoot_doctors_disagree(
        current=["Dr. WrongName"],
        parsed_surnames=["Pegram", "Iyengar"],
    ) is True


def test_disagree_false_when_shoot_matches():
    assert _shoot_doctors_disagree(
        current=["Dr. Pegram", "Dr. Iyengar"],
        parsed_surnames=["Pegram", "Iyengar"],
    ) is False


def test_disagree_false_when_shoot_matches_reverse_order():
    """Set comparison, not order comparison."""
    assert _shoot_doctors_disagree(
        current=["Dr. Iyengar", "Dr. Pegram"],
        parsed_surnames=["Pegram", "Iyengar"],
    ) is False


def test_disagree_false_when_parsed_empty():
    """Never overwrite with empty parsed set (protects against parse failures)."""
    assert _shoot_doctors_disagree(
        current=["Dr. Pegram"],
        parsed_surnames=[],
    ) is False
