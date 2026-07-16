"""SCRUM-59 — verify new KOL admin columns wire through the ORM correctly.

Covers:
- Default values on insert (display_order NULL, featured False, curated_fields [])
- Explicit values persist round-trip
- curated_fields accepts list mutation
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.kol import KOL
from utils.kol_public import kol_slug


@pytest.mark.asyncio
async def test_kol_admin_field_defaults(db_session: AsyncSession):
    kol = KOL(slug=kol_slug("Dr. Default"), name="Dr. Default")
    db_session.add(kol)
    await db_session.flush()
    await db_session.refresh(kol)

    assert kol.display_order is None
    assert kol.featured is False
    assert kol.curated_fields == []


@pytest.mark.asyncio
async def test_kol_admin_field_persistence(db_session: AsyncSession):
    kol = KOL(
        slug=kol_slug("Dr. Explicit"),
        name="Dr. Explicit",
        display_order=5,
        featured=True,
        curated_fields=["bio", "photo_url"],
    )
    db_session.add(kol)
    await db_session.flush()

    result = (
        await db_session.execute(
            select(KOL).where(KOL.slug == kol_slug("Dr. Explicit"))
        )
    ).scalar_one()

    assert result.display_order == 5
    assert result.featured is True
    assert set(result.curated_fields) == {"bio", "photo_url"}


@pytest.mark.asyncio
async def test_kol_curated_fields_replacement(db_session: AsyncSession):
    """Enrichment-guard pattern: PATCH adds field, second PATCH replaces list."""
    kol = KOL(slug=kol_slug("Dr. Curate"), name="Dr. Curate")
    db_session.add(kol)
    await db_session.flush()

    kol.curated_fields = [*kol.curated_fields, "bio"]
    await db_session.flush()
    assert kol.curated_fields == ["bio"]

    kol.curated_fields = [*kol.curated_fields, "region"]
    await db_session.flush()
    assert sorted(kol.curated_fields) == ["bio", "region"]
