"""Tests for WPR-11 — WP tag → namespaced tag mapping.

Covers:
- Rulebook classification (biomarkers, drugs, trials, conferences, stages)
- Fallback semantics (unmapped tag → None from classify_wp_tag)
- Resolver priority (DB > rulebook > wp:<slug>)
- Trial display-form casing (destiny-breast-06 → DESTINY-Breast-06)
- /api/public/wordpress/tags exposes namespaced_tag
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import api_headers
from jobs.wp_tag_namespace_resolver import (
    NamespacedTag,
    resolve_wp_tag,
    resolve_wp_tags_batch,
)
from jobs.wp_tag_namespace_rulebook import (
    NAMESPACE_BIOMARKER,
    NAMESPACE_CONFERENCE,
    NAMESPACE_DRUG,
    NAMESPACE_STAGE,
    NAMESPACE_TRIAL,
    _trial_display_form,
    classify_batch,
    classify_wp_tag,
)
from models.wordpress_projection import WordPressPost, WordPressPostTag, WordPressTag
from models.wp_tag_namespace_map import WpTagNamespaceMap
from test_public_wordpress import _insert_event


# ─────────────────────────────────────────────────────────────────────────────
# Rulebook — biomarkers
# ─────────────────────────────────────────────────────────────────────────────


class TestBiomarkerRules:
    def test_her2_variants(self):
        assert classify_wp_tag("her2").namespace == NAMESPACE_BIOMARKER
        assert classify_wp_tag("her2").value == "HER2+"
        assert classify_wp_tag("her2-low").value == "HER2-low"
        assert classify_wp_tag("her2-ultra-low").value == "HER2-ultra-low"
        assert classify_wp_tag("her2-negative").value == "HER2-negative"

    def test_hr_variants(self):
        assert classify_wp_tag("hr").value == "HR+"
        assert classify_wp_tag("hr-positive").value == "HR+"

    def test_common_mutations(self):
        assert classify_wp_tag("esr1").value == "ESR1"
        assert classify_wp_tag("pik3ca").value == "PIK3CA"
        assert classify_wp_tag("brca1").value == "BRCA1"
        assert classify_wp_tag("pd-l1").value == "PD-L1"

    def test_tnbc_synonyms(self):
        assert classify_wp_tag("tnbc").value == "TNBC"
        assert classify_wp_tag("triple-negative").value == "TNBC"


# ─────────────────────────────────────────────────────────────────────────────
# Rulebook — drugs
# ─────────────────────────────────────────────────────────────────────────────


class TestDrugRules:
    def test_t_dxd_variants(self):
        assert classify_wp_tag("t-dxd").namespace == NAMESPACE_DRUG
        assert classify_wp_tag("t-dxd").value == "T-DXd"
        assert classify_wp_tag("trastuzumab-deruxtecan").value == "T-DXd"
        assert classify_wp_tag("enhertu").value == "Enhertu"

    def test_cdk46_inhibitors(self):
        assert classify_wp_tag("palbociclib").value == "Palbociclib"
        assert classify_wp_tag("ribociclib").value == "Ribociclib"
        assert classify_wp_tag("abemaciclib").value == "Abemaciclib"

    def test_brand_vs_generic_both_classify(self):
        """Brand names AND generics both resolve to drug: namespace."""
        assert classify_wp_tag("herceptin").namespace == NAMESPACE_DRUG
        assert classify_wp_tag("trastuzumab").namespace == NAMESPACE_DRUG


# ─────────────────────────────────────────────────────────────────────────────
# Rulebook — trials
# ─────────────────────────────────────────────────────────────────────────────


class TestTrialRules:
    def test_destiny_breast_pattern(self):
        r = classify_wp_tag("destiny-breast-06")
        assert r.namespace == NAMESPACE_TRIAL
        assert r.value == "DESTINY-Breast-06"

    def test_serena_pattern(self):
        r = classify_wp_tag("serena-6")
        assert r.namespace == NAMESPACE_TRIAL
        assert r.value == "SERENA-6"

    def test_keynote_pattern(self):
        r = classify_wp_tag("keynote-522")
        assert r.value == "KEYNOTE-522"

    def test_monarche_pattern(self):
        assert classify_wp_tag("monarche").namespace == NAMESPACE_TRIAL

    def test_non_trial_not_classified(self):
        assert classify_wp_tag("random-thing") is None


class TestTrialDisplayForm:
    def test_uppercase_first_token(self):
        assert _trial_display_form("destiny-breast-06") == "DESTINY-Breast-06"

    def test_serena_number(self):
        assert _trial_display_form("serena-6") == "SERENA-6"

    def test_purely_numeric_kept(self):
        assert _trial_display_form("keynote-522") == "KEYNOTE-522"


# ─────────────────────────────────────────────────────────────────────────────
# Rulebook — conferences
# ─────────────────────────────────────────────────────────────────────────────


class TestConferenceRules:
    def test_asco_bare(self):
        assert classify_wp_tag("asco").namespace == NAMESPACE_CONFERENCE
        assert classify_wp_tag("asco").value == "ASCO"

    def test_asco_year(self):
        r = classify_wp_tag("asco2026")
        assert r.value == "ASCO-2026"

    def test_esmo(self):
        assert classify_wp_tag("esmo").value == "ESMO"
        assert classify_wp_tag("esmo-breast").value == "ESMO-Breast"

    def test_sabcs_alt(self):
        assert classify_wp_tag("sabcs").value == "SABCS"
        assert classify_wp_tag("san-antonio").value == "SABCS"


# ─────────────────────────────────────────────────────────────────────────────
# Rulebook — stages
# ─────────────────────────────────────────────────────────────────────────────


class TestStageRules:
    def test_mbc_alias(self):
        assert classify_wp_tag("mbc").namespace == NAMESPACE_STAGE
        assert classify_wp_tag("mbc").value == "metastatic"

    def test_adjuvant(self):
        assert classify_wp_tag("adjuvant").value == "adjuvant"

    def test_high_risk(self):
        assert classify_wp_tag("high-risk").value == "high-risk"


# ─────────────────────────────────────────────────────────────────────────────
# Unmapped
# ─────────────────────────────────────────────────────────────────────────────


class TestUnmapped:
    def test_random_returns_none(self):
        assert classify_wp_tag("random-editorial-tag") is None

    def test_empty_returns_none(self):
        assert classify_wp_tag("") is None
        assert classify_wp_tag(None) is None

    def test_case_normalized(self):
        """Uppercase input is normalized to lowercase before matching."""
        assert classify_wp_tag("HER2") == classify_wp_tag("her2")


class TestClassifyBatch:
    def test_returns_only_matched(self):
        result = classify_batch(["her2", "random", "t-dxd", ""])
        assert set(result.keys()) == {"her2", "t-dxd"}


# ─────────────────────────────────────────────────────────────────────────────
# Resolver — DB priority + rulebook fallback + wp: fallback
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolver_db_wins_over_rulebook(db_session: AsyncSession):
    """Curator-sourced DB row overrides what the rulebook would produce."""
    db_session.add(
        WpTagNamespaceMap(
            wp_tag_slug="her2",
            canonical_namespace="topic",
            canonical_value="HER2 special override",
            source="curator",
        )
    )
    await db_session.commit()

    result = await resolve_wp_tag(db_session, "her2")
    assert result.namespace == "topic"
    assert result.value == "HER2 special override"
    assert result.source == "db"


@pytest.mark.asyncio
async def test_resolver_falls_back_to_rulebook(db_session: AsyncSession):
    """No DB row → rulebook match wins."""
    result = await resolve_wp_tag(db_session, "esr1")
    assert result.namespace == "biomarker"
    assert result.value == "ESR1"
    assert result.source == "rule"


@pytest.mark.asyncio
async def test_resolver_falls_back_to_wp_prefix(db_session: AsyncSession):
    """Unknown to both DB and rulebook → wp:<slug>."""
    result = await resolve_wp_tag(db_session, "some-random-editorial-tag")
    assert result.namespace == "wp"
    assert result.value == "some-random-editorial-tag"
    assert result.source == "wp_fallback"


@pytest.mark.asyncio
async def test_resolver_never_loses_a_tag(db_session: AsyncSession):
    """Whatever slug goes in, something comes out — no None."""
    for slug in ["", "her2", "unknown-x", "destiny-breast-06"]:
        result = await resolve_wp_tag(db_session, slug)
        assert result is not None


@pytest.mark.asyncio
async def test_resolver_batch_one_db_lookup(db_session: AsyncSession):
    """Batch resolver returns the same shape per slug as the single resolver."""
    db_session.add(
        WpTagNamespaceMap(
            wp_tag_slug="curator-override",
            canonical_namespace="topic",
            canonical_value="Override",
            source="curator",
        )
    )
    await db_session.commit()

    slugs = ["her2", "t-dxd", "unknown-x", "curator-override"]
    results = await resolve_wp_tags_batch(db_session, slugs)

    assert results["her2"].as_qualified() == "biomarker:HER2+"
    assert results["t-dxd"].as_qualified() == "drug:T-DXd"
    assert results["unknown-x"].as_qualified() == "wp:unknown-x"
    assert results["curator-override"].as_qualified() == "topic:Override"


@pytest.mark.asyncio
async def test_resolver_qualified_form(db_session: AsyncSession):
    r = await resolve_wp_tag(db_session, "her2")
    assert r.as_qualified() == "biomarker:HER2+"


# ─────────────────────────────────────────────────────────────────────────────
# /api/public/wordpress/tags — namespaced_tag in response
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tags_endpoint_includes_namespaced_projection(
    client: AsyncClient, db_session: AsyncSession
):
    """Every returned tag row should include a namespaced_tag value —
    either a rule-mapped one, a DB-mapped one, or a wp:<slug> fallback."""
    base = datetime(2026, 7, 20, tzinfo=timezone.utc)
    await _insert_event(
        db_session,
        post_id=8001,
        slug="p1",
        title="P1",
        modified_gmt=base,
        tags=["her2", "some-editorial-thing"],
    )
    await db_session.commit()

    response = await client.get(
        "/api/public/wordpress/tags", headers=api_headers()
    )
    body = response.json()
    by_slug = {item["slug"]: item for item in body["items"]}

    # Rule-mapped tag → biomarker:HER2+
    assert by_slug["her2"]["namespaced_tag"] == "biomarker:HER2+"
    # Unmapped tag → wp:<slug> fallback
    assert (
        by_slug["some-editorial-thing"]["namespaced_tag"]
        == "wp:some-editorial-thing"
    )


@pytest.mark.asyncio
async def test_tags_endpoint_respects_curator_db_override(
    client: AsyncClient, db_session: AsyncSession
):
    """A curator-sourced DB row wins over the inline rulebook."""
    base = datetime(2026, 7, 20, tzinfo=timezone.utc)
    await _insert_event(
        db_session,
        post_id=8010,
        slug="p2",
        title="P2",
        modified_gmt=base,
        tags=["her2"],
    )
    db_session.add(
        WpTagNamespaceMap(
            wp_tag_slug="her2",
            canonical_namespace="topic",
            canonical_value="HER2 override",
            source="curator",
        )
    )
    await db_session.commit()

    response = await client.get(
        "/api/public/wordpress/tags", headers=api_headers()
    )
    body = response.json()
    her2 = next(item for item in body["items"] if item["slug"] == "her2")
    assert her2["namespaced_tag"] == "topic:HER2 override"
