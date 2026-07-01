"""KOL slug assignment and backfill."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.kol import KOL
from utils.kol_public import build_kol_slug_map


def assign_slugs(kols: list[KOL]) -> None:
    """Set kol.slug from names (handles collisions with -2, -3, …)."""
    slug_map = build_kol_slug_map(kols)
    for kol in kols:
        kol.slug = slug_map[kol.id]


async def backfill_all_kol_slugs(db: AsyncSession) -> int:
    """Recompute slugs for every KOL row. Returns count updated."""
    kols = list((await db.execute(select(KOL).order_by(KOL.name.asc()))).scalars().all())
    assign_slugs(kols)
    return len(kols)
