"""Tests for tag_taxonomy (SCRUM-73)."""

from __future__ import annotations

from services.tag_taxonomy import (
    CANONICAL_NAMESPACES,
    normalize_and_validate_tags,
    normalize_tags,
)


def test_canonical_namespaces_ticket_scope():
    """Locked to the 6 namespaces named in SCRUM-73."""
    assert CANONICAL_NAMESPACES == frozenset(
        {"biomarker", "drug", "trial", "doctor", "conference", "topic"}
    )


def test_normalize_kebab_biomarker():
    result = normalize_and_validate_tags(["biomarker:HER2-Low"])
    assert result.normalized == ["biomarker:her2-low"]
    assert result.ok


def test_normalize_biomarker_alias():
    result = normalize_and_validate_tags(["biomarker:HER2LOW", "biomarker:TNBC"])
    assert result.normalized == ["biomarker:her2-low", "biomarker:triple-negative"]


def test_normalize_drug_brand_to_generic():
    result = normalize_and_validate_tags(
        ["drug:Enhertu", "drug:Trastuzumab-Deruxtecan"]
    )
    assert result.normalized == ["drug:t-dxd"]


def test_normalize_doctor_title_cases_surname():
    result = normalize_and_validate_tags(["doctor:pegram", "doctor:TRAINA"])
    assert result.normalized == ["doctor:Pegram", "doctor:Traina"]


def test_normalize_doctor_typo_correction():
    result = normalize_and_validate_tags(["doctor:kree", "doctor:MAKLIN"])
    assert result.normalized == ["doctor:Krie", "doctor:Makhlin"]


def test_normalize_doctor_preserves_hyphen_and_apostrophe():
    result = normalize_and_validate_tags(
        ["doctor:Garrido-Castro", "doctor:o'shaughnessey"]
    )
    assert result.normalized == ["doctor:Garrido-Castro", "doctor:O'Shaughnessy"]


def test_normalize_trial_requires_nct_shape():
    result = normalize_and_validate_tags(["trial:NCT01234567"])
    assert result.normalized == ["trial:nct01234567"]
    assert result.ok


def test_normalize_trial_rejects_bad_shape():
    result = normalize_and_validate_tags(["trial:destiny-04"])
    assert result.normalized == []
    assert len(result.rejected) == 1
    assert "NCT" in result.rejected[0][1]


def test_normalize_conference_alias():
    result = normalize_and_validate_tags(["conference:ASCO2026", "conference:sabcs-25"])
    assert result.normalized == ["conference:asco-2026", "conference:sabcs-2025"]


def test_rejects_unknown_namespace():
    result = normalize_and_validate_tags(["brand:enhertu", "stage:iv"])
    assert result.normalized == []
    assert {r[1] for r in result.rejected} == {
        "unknown namespace 'brand'",
        "unknown namespace 'stage'",
    }


def test_rejects_missing_colon():
    result = normalize_and_validate_tags(["her2low", "randomtag"])
    assert result.normalized == []
    assert all("not namespaced" in r[1] for r in result.rejected)


def test_rejects_empty_value():
    result = normalize_and_validate_tags(["drug:", "biomarker:"])
    assert result.normalized == []
    assert len(result.rejected) == 2


def test_dedupes_after_normalization():
    """Two variants of the same canonical tag collapse to one."""
    result = normalize_and_validate_tags(
        ["drug:Enhertu", "drug:t-dxd", "drug:Trastuzumab-Deruxtecan"]
    )
    assert result.normalized == ["drug:t-dxd"]


def test_preserves_first_seen_order():
    result = normalize_and_validate_tags(
        ["drug:t-dxd", "doctor:Pegram", "biomarker:her2-low"]
    )
    assert result.normalized == [
        "drug:t-dxd",
        "doctor:Pegram",
        "biomarker:her2-low",
    ]


def test_kebab_validator_rejects_underscores_and_spaces():
    result = normalize_and_validate_tags(["biomarker:her2_low", "drug:t dxd"])
    assert result.normalized == []
    assert all("kebab-case" in r[1] for r in result.rejected)


def test_tolerant_normalize_drops_bad_silently():
    """`normalize_tags` is the tagger-facing variant — silently drops
    malformed tags so one bad row doesn't block a whole shoot's propagation.
    """
    result = normalize_tags(
        ["drug:Enhertu", "not-a-tag", "unknown:ns", "biomarker:HER2LOW"]
    )
    assert result == ["drug:t-dxd", "biomarker:her2-low"]


def test_empty_input_returns_empty():
    assert normalize_tags([]) == []
    assert normalize_tags(None) == []
    r = normalize_and_validate_tags(None)
    assert r.normalized == []
    assert r.rejected == []


def test_non_string_tag_rejected_gracefully():
    result = normalize_and_validate_tags(["drug:t-dxd", 123, None])  # type: ignore[list-item]
    assert result.normalized == ["drug:t-dxd"]
    assert len(result.rejected) == 2
