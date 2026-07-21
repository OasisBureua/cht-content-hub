"""Tests for tag_taxonomy (SCRUM-73, revised 2026-07-21).

Verifies the freeform-value / namespace-enforcement contract:
  - Recognized namespaces pass, unknown reject with reason
  - Values keep freeform characters (spaces, +, mixed case)
  - Alias corrections collapse variants to canonical values
  - Case-insensitive dedupe
  - Doctor namespace is Title-cased with typo correction
  - Malformed (empty value, control chars) rejected
"""

from __future__ import annotations

from services.tag_taxonomy import (
    CANONICAL_NAMESPACES,
    normalize_and_validate_tags,
    normalize_tags,
)


# ─── namespace enforcement ──────────────────────────────────────────────────


def test_canonical_namespaces_full_set():
    """All 10 namespaces recognized: 7 editorial + wp/yt + other."""
    assert CANONICAL_NAMESPACES == frozenset(
        {
            "biomarker",
            "drug",
            "trial",
            "doctor",
            "conference",
            "topic",
            "stage",
            "wp",
            "yt",
            "other",
        }
    )


def test_rejects_unknown_namespace():
    result = normalize_and_validate_tags(["brand:enhertu", "unknown:foo"])
    assert result.normalized == []
    assert {r[1] for r in result.rejected} == {
        "unknown namespace 'brand'",
        "unknown namespace 'unknown'",
    }


def test_rejects_missing_colon():
    result = normalize_and_validate_tags(["her2low", "randomtag"])
    assert result.normalized == []
    assert all("not namespaced" in r[1] for r in result.rejected)


def test_rejects_empty_value():
    result = normalize_and_validate_tags(["drug:", "biomarker:  "])
    assert result.normalized == []
    assert len(result.rejected) == 2


def test_rejects_control_chars_in_value():
    result = normalize_and_validate_tags(["topic:has\nnewline"])
    assert result.normalized == []
    assert "newline" in result.rejected[0][1]


# ─── freeform values pass through (this is the point of the revision) ──────


def test_biomarker_freeform_preserved():
    """Live data has values like 'HER2+', 'HER2-low', 'High-Risk / CNS'. Keep them."""
    result = normalize_and_validate_tags(
        ["biomarker:HER2+", "biomarker:High-Risk / CNS"]
    )
    assert result.normalized == [
        "biomarker:HER2+",
        "biomarker:High-Risk / CNS",
    ]
    assert result.ok


def test_topic_freeform_with_spaces():
    result = normalize_and_validate_tags(["topic:metastatic breast cancer"])
    assert result.normalized == ["topic:metastatic breast cancer"]
    assert result.ok


def test_stage_freeform_camelcase():
    result = normalize_and_validate_tags(["stage:mBC", "stage:EBC"])
    assert result.normalized == ["stage:mBC", "stage:EBC"]


def test_wp_yt_namespaces_freeform():
    result = normalize_and_validate_tags(
        ["wp:her2-positive", "yt:HER2 Positive Therapy"]
    )
    assert result.normalized == ["wp:her2-positive", "yt:HER2 Positive Therapy"]


def test_other_namespace_freeform():
    result = normalize_and_validate_tags(["other:some-imported-value"])
    assert result.normalized == ["other:some-imported-value"]


# ─── alias corrections still apply ─────────────────────────────────────────


def test_drug_alias_enhertu_to_tdxd():
    result = normalize_and_validate_tags(
        ["drug:Enhertu", "drug:trastuzumab-deruxtecan"]
    )
    assert result.normalized == ["drug:t-dxd"]


def test_biomarker_alias_tnbc_to_triple_negative():
    result = normalize_and_validate_tags(["biomarker:TNBC", "biomarker:tripleneg"])
    assert result.normalized == ["biomarker:triple-negative"]


def test_biomarker_alias_her2low_variants():
    result = normalize_and_validate_tags(
        ["biomarker:her2low", "biomarker:HER2 low", "biomarker:HER2-low"]
    )
    assert result.normalized == ["biomarker:HER2-low"]


def test_conference_alias_asco2026():
    result = normalize_and_validate_tags(
        ["conference:asco-2026", "conference:ASCO2026"]
    )
    assert result.normalized == ["conference:ASCO 2026"]


# ─── doctor namespace: Title-case + typo correction ────────────────────────


def test_doctor_title_cased_from_lowercase():
    result = normalize_and_validate_tags(["doctor:pegram", "doctor:TRAINA"])
    assert result.normalized == ["doctor:Pegram", "doctor:Traina"]


def test_doctor_typo_correction():
    result = normalize_and_validate_tags(["doctor:kree", "doctor:MAKLIN"])
    assert result.normalized == ["doctor:Krie", "doctor:Makhlin"]


def test_doctor_apostrophe_and_hyphen_preserved():
    result = normalize_and_validate_tags(
        ["doctor:Garrido-Castro", "doctor:o'shaughnessey"]
    )
    assert result.normalized == [
        "doctor:Garrido-Castro",
        "doctor:O'Shaughnessy",
    ]


# ─── dedupe ────────────────────────────────────────────────────────────────


def test_dedupe_case_insensitive_on_value():
    """biomarker:HER2+ and biomarker:her2+ collapse — first-seen wins."""
    result = normalize_and_validate_tags(
        ["biomarker:HER2+", "biomarker:her2+"]
    )
    assert result.normalized == ["biomarker:HER2+"]


def test_dedupe_preserves_first_seen_order():
    result = normalize_and_validate_tags(
        ["drug:t-dxd", "doctor:Pegram", "biomarker:HER2-low"]
    )
    assert result.normalized == [
        "drug:t-dxd",
        "doctor:Pegram",
        "biomarker:HER2-low",
    ]


def test_dedupe_after_alias_normalization():
    """Enhertu + trastuzumab-deruxtecan + t-dxd → one entry."""
    result = normalize_and_validate_tags(
        ["drug:Enhertu", "drug:t-dxd", "drug:trastuzumab-deruxtecan"]
    )
    assert result.normalized == ["drug:t-dxd"]


# ─── tolerant normalizer for tagger loop ───────────────────────────────────


def test_tolerant_normalize_drops_bad_silently():
    result = normalize_tags(
        ["drug:Enhertu", "not-a-tag", "unknown:ns", "biomarker:HER2+"]
    )
    assert result == ["drug:t-dxd", "biomarker:HER2+"]


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


# ─── real-world spot checks (from actual devapp data) ──────────────────────


def test_real_world_seed_data_passes_through():
    real_clip_tags = [
        "biomarker:HER2-low",
        "biomarker:HER2-ultralow",
        "biomarker:High-Risk / CNS",
        "doctor:Bardia",
        "doctor:Callahan",
        "drug:T-DXD",
        "topic:CNS",
    ]
    result = normalize_and_validate_tags(real_clip_tags)
    # drug:T-DXD preserved verbatim — lowercase lookup key `t-dxd` isn't in
    # DRUG_CORRECTIONS (only variant aliases like `enhertu` map to `t-dxd`).
    # If the DB has both `drug:T-DXD` and `drug:Enhertu`, they'd collapse to
    # `drug:t-dxd` on write (Enhertu → t-dxd, then dedupe with T-DXD via
    # case-insensitive dedupe key). See dedupe tests.
    assert set(result.normalized) == {
        "biomarker:HER2-low",
        "biomarker:HER2-ultralow",
        "biomarker:High-Risk / CNS",
        "doctor:Bardia",
        "doctor:Callahan",
        "drug:T-DXD",
        "topic:CNS",
    }
    assert result.ok


def test_real_world_seed_data_with_stage_and_topic():
    real_clip_tags = [
        "biomarker:HER2+",
        "biomarker:HER2-low",
        "doctor:Bardia",
        "drug:T-DXD",
        "stage:mBC",
        "topic:metastatic breast cancer",
    ]
    result = normalize_and_validate_tags(real_clip_tags)
    assert set(result.normalized) == {
        "biomarker:HER2+",
        "biomarker:HER2-low",
        "doctor:Bardia",
        "drug:T-DXD",
        "stage:mBC",
        "topic:metastatic breast cancer",
    }
