"""One-time KOL backfill: bios, title/institution corrections, publications."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hcp_intel.kol_bio_backfill import BIO_TEXT, PROFILES, run
from models.kol import KOL


@pytest.mark.asyncio
async def test_backfill_writes_bio_for_matching_slug(db_session: AsyncSession):
    kol = KOL(slug="bardia", name="Dr. Aditya Bardia", bio="old placeholder bio")
    db_session.add(kol)
    await db_session.flush()

    results = await run(session=db_session)

    assert results["bardia"] == ["bio", "publications"]
    row = (
        await db_session.execute(select(KOL).where(KOL.slug == "bardia"))
    ).scalar_one()
    assert row.bio == BIO_TEXT["bardia"]
    assert row.publications == PROFILES["bardia"]["publications"]
    assert {"bio", "publications"} <= set(row.curated_fields)


@pytest.mark.asyncio
async def test_backfill_applies_title_and_institution_corrections(db_session: AsyncSession):
    kol = KOL(
        slug="krie",
        name="Dr. Amy Krie",
        title="Clinical Director, Avera Breast Center",
        institution="Avera Cancer Institute / Avera Breast Center",
    )
    db_session.add(kol)
    await db_session.flush()

    results = await run(session=db_session)

    assert {"title", "institution"} <= set(results["krie"])
    assert kol.title == PROFILES["krie"]["title"]
    assert kol.institution == PROFILES["krie"]["institution"]
    assert {"title", "institution"} <= set(kol.curated_fields)


@pytest.mark.asyncio
async def test_backfill_skips_slug_with_no_matching_kol(db_session: AsyncSession):
    # No KOL row seeded for any BIO_TEXT slug — should skip, not raise.
    results = await run(session=db_session)
    assert all(v == [] for v in results.values())


@pytest.mark.asyncio
async def test_backfill_is_idempotent_on_rerun(db_session: AsyncSession):
    kol = KOL(slug="robson", name="Dr. Mark Robson", bio="old placeholder bio")
    db_session.add(kol)
    await db_session.flush()

    await run(session=db_session)
    second = await run(session=db_session)

    # Second run: value already matches, apply_kol_field_update reports no change.
    assert second["robson"] == []


@pytest.mark.asyncio
async def test_backfill_covers_all_39_live_slugs():
    assert len(BIO_TEXT) == 39
    assert len(set(BIO_TEXT.keys())) == 39
    for slug, bio in BIO_TEXT.items():
        assert bio.strip(), f"{slug} has an empty bio"
        assert bio.startswith("Dr. "), f"{slug} bio doesn't start with 'Dr. '"


def test_profiles_fit_the_kol_columns():
    for slug, profile in PROFILES.items():
        assert len(profile.get("title", "")) <= 100, f"{slug} title exceeds kols.title"
        for pub in profile["publications"]:
            assert pub["title"].strip(), f"{slug} has a publication with no title"
            assert pub["url"].startswith("https://pubmed.ncbi.nlm.nih.gov/"), slug
        years = [p["year"] or 0 for p in profile["publications"]]
        assert years == sorted(years, reverse=True), f"{slug} publications not newest first"
