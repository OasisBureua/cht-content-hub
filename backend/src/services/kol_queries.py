"""KOL directory query layer — shared by public API handlers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.sql.functions import coalesce
from sqlalchemy.ext.asyncio import AsyncSession

from hcp_intel.models import HCPSignal
from models.kol import KOL, KOLGroup, KOLGroupMember
from models.shoot import Shoot
from schemas.public import (
    PublicKOL,
    PublicKOLIntel,
    PublicKOLPublication,
    PublicKOLPublicationList,
    PublicKOLRegion,
)
from services.kol_regions import REGIONS
from utils.kol_public import build_kol_slug_map, kol_to_public
from utils.time import ensure_utc


@dataclass(frozen=True)
class ShootStats:
    shoot_count: int = 0
    first_shoot_at: datetime | None = None


async def list_kols(
    db: AsyncSession,
    *,
    region: str | None = None,
    institution: str | None = None,
    q: str | None = None,
) -> list[KOL]:
    stmt = select(KOL).order_by(KOL.name.asc())
    if region:
        stmt = stmt.where(KOL.region == region)
    if institution:
        stmt = stmt.where(KOL.institution == institution)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                KOL.name.ilike(like),
                KOL.institution.ilike(like),
                KOL.specialty.ilike(like),
                KOL.bio.ilike(like),
            )
        )
    return list((await db.execute(stmt)).scalars().all())


async def load_slug_index(db: AsyncSession) -> tuple[list[KOL], dict[str, str]]:
    kols = await list_kols(db)
    slugs = await build_kol_slug_map(kols)
    return kols, slugs


async def get_kol_by_slug(db: AsyncSession, slug: str) -> tuple[KOL, str]:
    kols, slugs = await load_slug_index(db)
    for kol in kols:
        if slugs.get(kol.id) == slug:
            return kol, slug
    raise HTTPException(status_code=404, detail="KOL not found")


async def shoot_stats_for_kols(
    db: AsyncSession, kol_ids: list[str]
) -> dict[str, ShootStats]:
    if not kol_ids:
        return {}

    rows = await db.execute(
        select(
            KOLGroupMember.kol_id.label("kol_id"),
            func.count(func.distinct(Shoot.id)).label("shoot_count"),
            func.min(coalesce(Shoot.shoot_date, Shoot.created_at)).label("first_shoot_at"),
        )
        .join(KOLGroup, KOLGroup.id == KOLGroupMember.kol_group_id)
        .join(Shoot, Shoot.kol_group_id == KOLGroup.id)
        .where(KOLGroupMember.kol_id.in_(kol_ids))
        .group_by(KOLGroupMember.kol_id)
    )
    return {
        row.kol_id: ShootStats(
            shoot_count=int(row.shoot_count or 0),
            first_shoot_at=ensure_utc(row.first_shoot_at),
        )
        for row in rows
    }


async def shoot_stats_for_kol(db: AsyncSession, kol_id: str) -> ShootStats:
    row = (
        await db.execute(
            select(
                func.count(func.distinct(Shoot.id)).label("shoot_count"),
                func.min(coalesce(Shoot.shoot_date, Shoot.created_at)).label("first_shoot_at"),
            )
            .select_from(KOLGroupMember)
            .join(KOLGroup, KOLGroup.id == KOLGroupMember.kol_group_id)
            .join(Shoot, Shoot.kol_group_id == KOLGroup.id)
            .where(KOLGroupMember.kol_id == kol_id)
        )
    ).one()
    return ShootStats(
        shoot_count=int(row.shoot_count or 0),
        first_shoot_at=ensure_utc(row.first_shoot_at),
    )


def to_public_kol(
    kol: KOL, slug: str, stats: ShootStats, intel: PublicKOLIntel | None = None
) -> PublicKOL:
    return kol_to_public(
        kol=kol,
        slug=slug,
        shoot_count=stats.shoot_count,
        first_appeared_at=stats.first_shoot_at,
        intel=intel,
    )


def build_region_facets(items: list[PublicKOL]) -> list[PublicKOLRegion]:
    counts: dict[str, int] = {}
    for item in items:
        if item.region:
            counts[item.region] = counts.get(item.region, 0) + 1
    return [
        PublicKOLRegion(slug=r["slug"], label=r["label"], kol_count=counts[r["slug"]])
        for r in REGIONS
        if counts.get(r["slug"], 0) > 0
    ]


def collect_institutions(items: list[PublicKOL]) -> list[str]:
    return sorted({item.institution for item in items if item.institution})


def signal_to_publication(signal: HCPSignal) -> PublicKOLPublication | None:
    observed_at = ensure_utc(signal.observed_at)
    if observed_at is None:
        return None
    entities = signal.entities_json if isinstance(signal.entities_json, dict) else {}
    return PublicKOLPublication(
        title=signal.title or "(untitled)",
        url=signal.url,
        journal=entities.get("journal"),
        published_at=observed_at,
        is_first_author=bool(entities.get("is_first_author")),
        is_last_author=bool(entities.get("is_last_author")),
    )


async def list_publications(
    db: AsyncSession,
    hcp_npi: str,
    *,
    limit: int,
    offset: int,
) -> PublicKOLPublicationList:
    base_filter = (
        HCPSignal.hcp_npi == hcp_npi,
        HCPSignal.signal_type == "publication",
    )
    rows = list(
        (
            await db.execute(
                select(HCPSignal)
                .where(*base_filter)
                .order_by(HCPSignal.observed_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
    )
    total = (
        await db.execute(
            select(func.count()).select_from(HCPSignal).where(*base_filter)
        )
    ).scalar() or 0

    items = [pub for row in rows if (pub := signal_to_publication(row)) is not None]
    return PublicKOLPublicationList(items=items, total=int(total))
