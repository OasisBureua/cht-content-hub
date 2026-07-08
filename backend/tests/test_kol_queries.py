"""Tests for services.kol_queries."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from hcp_intel.models import HCPSignal
from models.kol import KOL
from schemas.public import PublicKOL
from services import kol_queries


def test_build_region_facets():
    items = [
        PublicKOL(
            id="1",
            slug="a",
            name="A",
            title=None,
            specialty=None,
            institution="UCSF",
            bio=None,
            photo_url=None,
            region="california",
            region_label="California",
            shoot_count=1,
            first_appeared_at=None,
            is_new=False,
        ),
        PublicKOL(
            id="2",
            slug="b",
            name="B",
            title=None,
            specialty=None,
            institution="MD Anderson",
            bio=None,
            photo_url=None,
            region="texas",
            region_label="Texas",
            shoot_count=1,
            first_appeared_at=None,
            is_new=False,
        ),
    ]
    facets = kol_queries.build_region_facets(items)
    slugs = {f.slug for f in facets}
    assert slugs == {"california", "texas"}
    assert all(f.kol_count == 1 for f in facets)


def test_collect_institutions():
    items = [
        PublicKOL(
            id="1",
            slug="a",
            name="A",
            title=None,
            specialty=None,
            institution="UCSF",
            bio=None,
            photo_url=None,
            region="california",
            region_label="California",
            shoot_count=0,
            first_appeared_at=None,
            is_new=False,
        ),
        PublicKOL(
            id="2",
            slug="b",
            name="B",
            title=None,
            specialty=None,
            institution="MD Anderson",
            bio=None,
            photo_url=None,
            region="texas",
            region_label="Texas",
            shoot_count=0,
            first_appeared_at=None,
            is_new=False,
        ),
    ]
    assert kol_queries.collect_institutions(items) == ["MD Anderson", "UCSF"]


def test_signal_to_publication():
    signal = HCPSignal(
        hcp_npi="1234567890",
        signal_type="publication",
        observed_at=datetime(2024, 3, 1, tzinfo=timezone.utc),
        source="pubmed",
        title="Study Title",
        url="https://example.com/paper",
        entities_json={"journal": "NEJM", "is_first_author": True},
    )
    pub = kol_queries.signal_to_publication(signal)
    assert pub is not None
    assert pub.title == "Study Title"
    assert pub.journal == "NEJM"
    assert pub.is_first_author is True


def test_signal_to_publication_skips_missing_observed_at():
    signal = HCPSignal(
        hcp_npi="1234567890",
        signal_type="publication",
        observed_at=None,  # type: ignore[arg-type]
        source="pubmed",
        title="No date",
    )
    assert kol_queries.signal_to_publication(signal) is None


@pytest.mark.asyncio
async def test_list_kols_filters(db_session, sample_kol, kol_with_shoot):
    by_region = await kol_queries.list_kols(db_session, region="california")
    assert len(by_region) == 1
    assert by_region[0].name == "Dr. Jane Smith"

    by_query = await kol_queries.list_kols(db_session, q="Mouabbi")
    assert len(by_query) == 1
    assert by_query[0].name == "Dr. Jason Mouabbi"


@pytest.mark.asyncio
async def test_get_kol_by_slug(db_session, sample_kol):
    slug = sample_kol.slug
    kol, resolved = await kol_queries.get_kol_by_slug(db_session, slug)
    assert kol.id == sample_kol.id
    assert resolved == slug


@pytest.mark.asyncio
async def test_get_kol_by_slug_not_found(db_session):
    with pytest.raises(HTTPException) as exc:
        await kol_queries.get_kol_by_slug(db_session, "missing-slug")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_shoot_stats_for_kol(db_session, kol_with_shoot):
    stats = await kol_queries.shoot_stats_for_kol(db_session, kol_with_shoot.id)
    assert stats.shoot_count == 1
    assert stats.first_shoot_at is not None


@pytest.mark.asyncio
async def test_list_publications(db_session, kol_with_publications):
    result = await kol_queries.list_publications(
        db_session, kol_with_publications.hcp_npi, limit=10, offset=0
    )
    assert result.total == 2
    assert [p.title for p in result.items] == ["Recent Paper", "Older Paper"]
    assert result.items[0].journal == "JCO"
