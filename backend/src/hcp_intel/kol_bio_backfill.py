"""One-time backfill: KOL bios, title/institution corrections, publications.

Data lives in `kol_profiles.json` next to this file, keyed by KOL slug:

    {"bio": str, "title"?: str, "institution"?: str,
     "publications": [{"title", "journal", "year", "url"}]}

Bios are written in our own words from current, sourced facts. Publications
are PubMed records where the KOL's own author entry carries an affiliation
they held, or their ORCID; newest first.

Run once, manually, against a real environment:

    python -m hcp_intel.kol_bio_backfill

Writes through `apply_kol_field_update(source="admin")`, so every written
field is marked curated and sync jobs will not overwrite it. Skips KOLs with
no row. Re-running is a no-op for fields that already match.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from admin.cache import notify_cht_cache_clear
from database import async_session_maker
from models.kol import KOL
from services.kol_write import apply_kol_field_update

log = logging.getLogger(__name__)

PROFILES: dict[str, dict[str, Any]] = json.loads(
    (Path(__file__).with_name("kol_profiles.json")).read_text(encoding="utf-8")
)
BIO_TEXT: dict[str, str] = {slug: p["bio"] for slug, p in PROFILES.items()}

_FIELDS = ("bio", "title", "institution", "publications")


async def _apply(session: AsyncSession) -> dict[str, list[str]]:
    results: dict[str, list[str]] = {}
    rows = (
        await session.execute(select(KOL).where(KOL.slug.in_(PROFILES.keys())))
    ).scalars().all()
    by_slug = {kol.slug: kol for kol in rows}

    for slug, profile in PROFILES.items():
        kol = by_slug.get(slug)
        if kol is None:
            log.warning("kol_bio_backfill: no KOL row for slug=%s, skipping", slug)
            continue
        updates = {k: profile[k] for k in _FIELDS if k in profile}
        results[slug] = apply_kol_field_update(kol, updates, source="admin")

    return results


async def run(session: AsyncSession | None = None) -> dict[str, list[str]]:
    """Apply PROFILES to every matching KOL. Returns {slug: changed_fields}.

    Pass `session` in tests to reuse the caller's transaction-scoped fixture
    session instead of opening a new connection via `async_session_maker` —
    keeps writes inside the fixture's rollback boundary instead of committing
    directly to the shared test database.
    """
    if session is not None:
        return await _apply(session)

    async with async_session_maker() as owned_session:
        results = await _apply(owned_session)
        await owned_session.commit()
    if any(results.values()):
        # Same cache bust as the admin PATCH, so the site shows the new data now.
        await notify_cht_cache_clear(scope="contenthub")
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    outcome = asyncio.run(run())
    changed_count = sum(1 for v in outcome.values() if v)
    log.info(
        "kol_bio_backfill complete: %d/%d KOLs updated", changed_count, len(outcome)
    )
