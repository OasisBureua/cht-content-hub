"""One-time bio backfill script: applies BIO_TEXT, respects curated locks."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hcp_intel.kol_bio_backfill import BIO_TEXT, run
from models.kol import KOL


@pytest.mark.asyncio
async def test_backfill_writes_bio_for_matching_slug(db_session: AsyncSession):
    kol = KOL(slug="bardia", name="Dr. Aditya Bardia", bio="old placeholder bio")
    db_session.add(kol)
    await db_session.flush()

    results = await run(session=db_session)

    assert results["bardia"] == ["bio"]
    row = (
        await db_session.execute(select(KOL).where(KOL.slug == "bardia"))
    ).scalar_one()
    assert row.bio == BIO_TEXT["bardia"]
    assert "bio" in row.curated_fields


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
