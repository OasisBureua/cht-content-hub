"""KOL directory query layer — shared by public API handlers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import Select, func, or_, select
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
from utils.kol_public import kol_to_public
from utils.time import ensure_utc

NEW_WINDOW_DAYS = 60


@dataclass(frozen=True)
class ShootStats:
    shoot_count: int = 0
    first_shoot_at: datetime | None = None


@dataclass(frozen=True)
class KolListFacets:
    total: int
    region_counts: dict[str, int]
    institutions: list[str]


def _new_only_cutoff() -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=NEW_WINDOW_DAYS)


def _shoot_stats_subquery():
    return (
        select(
            KOLGroupMember.kol_id.label("kol_id"),
            func.count(func.distinct(Shoot.id)).label("shoot_count"),
            func.min(coalesce(Shoot.shoot_date, Shoot.created_at)).label("first_shoot_at"),
        )
        .join(KOLGroup, KOLGroup.id == KOLGroupMember.kol_group_id)
        .join(Shoot, Shoot.kol_group_id == KOLGroup.id)
        .group_by(KOLGroupMember.kol_id)
        .subquery("kol_shoot_stats")
    )


def _apply_kol_filters(
    stmt: Select,
    *,
    region: str | None = None,
    institution: str | None = None,
    q: str | None = None,
    new_only: bool = False,
) -> Select:
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
    if new_only:
        stats = _shoot_stats_subquery()
        stmt = (
            stmt.join(stats, stats.c.kol_id == KOL.id)
            .where(stats.c.first_shoot_at >= _new_only_cutoff())
        )
    return stmt


async def list_kols(
    db: AsyncSession,
    *,
    region: str | None = None,
    institution: str | None = None,
    q: str | None = None,
    new_only: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> list[KOL]:
    stmt = _apply_kol_filters(
        select(KOL), region=region, institution=institution, q=q, new_only=new_only
    ).order_by(
        KOL.featured.desc(),
        KOL.display_order.asc().nulls_last(),
        KOL.name.asc(),
    )
    if limit is not None:
        stmt = stmt.limit(limit).offset(offset)
    return list((await db.execute(stmt)).scalars().all())


async def count_kols(
    db: AsyncSession,
    *,
    region: str | None = None,
    institution: str | None = None,
    q: str | None = None,
    new_only: bool = False,
) -> int:
    stmt = _apply_kol_filters(
        select(func.count()).select_from(KOL),
        region=region,
        institution=institution,
        q=q,
        new_only=new_only,
    )
    return int((await db.execute(stmt)).scalar() or 0)


async def region_facet_counts(
    db: AsyncSession,
    *,
    region: str | None = None,
    institution: str | None = None,
    q: str | None = None,
    new_only: bool = False,
) -> dict[str, int]:
    stmt = _apply_kol_filters(
        select(KOL.region, func.count())
        .where(KOL.region.isnot(None))
        .group_by(KOL.region),
        region=region,
        institution=institution,
        q=q,
        new_only=new_only,
    )
    rows = (await db.execute(stmt)).all()
    return {row[0]: int(row[1]) for row in rows}


async def institution_facet_values(
    db: AsyncSession,
    *,
    region: str | None = None,
    institution: str | None = None,
    q: str | None = None,
    new_only: bool = False,
) -> list[str]:
    stmt = _apply_kol_filters(
        select(KOL.institution)
        .where(KOL.institution.isnot(None))
        .distinct()
        .order_by(KOL.institution.asc()),
        region=region,
        institution=institution,
        q=q,
        new_only=new_only,
    )
    return [row[0] for row in (await db.execute(stmt)).all()]


async def get_kol_list_facets(
    db: AsyncSession,
    *,
    region: str | None = None,
    institution: str | None = None,
    q: str | None = None,
    new_only: bool = False,
) -> KolListFacets:
    filters = {
        "region": region,
        "institution": institution,
        "q": q,
        "new_only": new_only,
    }
    total, region_counts, institutions = await _gather_facets(db, **filters)
    return KolListFacets(
        total=total,
        region_counts=region_counts,
        institutions=institutions,
    )


async def _gather_facets(db: AsyncSession, **filters) -> tuple[int, dict[str, int], list[str]]:
    from services.db_reads import gather_reads

    total, region_counts, institutions = await gather_reads(
        db,
        lambda session: count_kols(session, **filters),
        lambda session: region_facet_counts(session, **filters),
        lambda session: institution_facet_values(session, **filters),
    )
    return total, region_counts, institutions


async def get_kol_by_slug(db: AsyncSession, slug: str) -> tuple[KOL, str]:
    kol = (
        await db.execute(select(KOL).where(KOL.slug == slug))
    ).scalar_one_or_none()
    if kol is None:
        raise HTTPException(status_code=404, detail="KOL not found")
    return kol, slug


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
    return build_region_facets_from_counts(counts)


def build_region_facets_from_counts(counts: dict[str, int]) -> list[PublicKOLRegion]:
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
    total_col = func.count().over().label("total")
    rows = (
        await db.execute(
            select(HCPSignal, total_col)
            .where(*base_filter)
            .order_by(HCPSignal.observed_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    if not rows:
        return PublicKOLPublicationList(items=[], total=0)

    total = int(rows[0].total or 0)
    items = [
        pub
        for row in rows
        if (pub := signal_to_publication(row[0])) is not None
    ]
    return PublicKOLPublicationList(items=items, total=total)
