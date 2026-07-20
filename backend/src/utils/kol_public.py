"""KOL helpers for public API handlers."""

from __future__ import annotations

from datetime import datetime, timezone

from models.kol import KOL
from schemas.public import PublicKOL, PublicKOLIntel
from services.kol_regions import label_for
from utils.time import ensure_utc


def kol_slug(name: str) -> str:
    cleaned = name.strip()
    if cleaned.lower().startswith("dr."):
        cleaned = cleaned[3:].strip()
    elif cleaned.lower().startswith("dr "):
        cleaned = cleaned[3:].strip()
    if "," in cleaned:
        cleaned = cleaned.split(",", 1)[0].strip()
    parts = cleaned.split()
    if not parts:
        return ""
    last = parts[-1]
    return "".join(c.lower() for c in last if c.isalnum() or c == "-")


def kol_to_public(
    kol: KOL,
    slug: str,
    shoot_count: int,
    first_appeared_at: datetime | None,
    new_window_days: int = 60,
    intel: PublicKOLIntel | None = None,
) -> PublicKOL:
    is_new = False
    first_appeared_at = ensure_utc(first_appeared_at)
    if first_appeared_at is not None:
        is_new = (datetime.now(timezone.utc) - first_appeared_at).days <= new_window_days
    return PublicKOL(
        id=kol.id,
        slug=slug,
        name=kol.name,
        title=kol.title,
        specialty=kol.specialty,
        institution=kol.institution,
        bio=kol.bio,
        photo_url=kol.photo_url,
        region=kol.region,
        region_label=kol.region_label or label_for(kol.region),
        shoot_count=shoot_count,
        first_appeared_at=first_appeared_at,
        is_new=is_new,
        display_order=kol.display_order,
        featured=bool(kol.featured),
        intel=intel,
    )


def build_kol_slug_map(kols: list[KOL]) -> dict[str, str]:
    slug_counts: dict[str, int] = {}
    out: dict[str, str] = {}
    for kol in sorted(kols, key=lambda k: k.name):
        base = kol_slug(kol.name) or kol.id[:8]
        n = slug_counts.get(base, 0) + 1
        slug_counts[base] = n
        out[kol.id] = base if n == 1 else f"{base}-{n}"
    return out
