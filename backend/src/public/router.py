"""Public KOL network API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from public.deps import verify_public_api_key
from public.limits import limiter
from schemas.public import (
    HCPUpsertRequest,
    HCPUpsertResponse,
    PublicKOL,
    PublicKOLList,
    PublicKOLPublicationList,
)
from services import hcp_upsert, kol_enrichment, kol_queries
from services.db_reads import gather_reads


router = APIRouter(prefix="/api/public", tags=["public-kol"])


@router.get("/kols", response_model=PublicKOLList)
@limiter.limit("100/minute")
async def get_public_kols(
    request: Request,
    _api_key: Annotated[str, Depends(verify_public_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
    region: str | None = Query(default=None),
    institution: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    new_only: bool = Query(default=False),
    include_intel: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> PublicKOLList:
    filters = {
        "region": region,
        "institution": institution,
        "q": q,
        "new_only": new_only,
    }

    facets, kols = await gather_reads(
        db,
        lambda session: kol_queries.get_kol_list_facets(session, **filters),
        lambda session: kol_queries.list_kols(
            session, **filters, limit=limit, offset=offset
        ),
    )
    if facets.total == 0:
        return PublicKOLList(items=[], total=0, regions=[], institutions=[])

    kol_ids = [k.id for k in kols]
    npis = [k.hcp_npi for k in kols if k.hcp_npi]

    if include_intel and npis:
        stats_by_id, intel_by_npi = await gather_reads(
            db,
            lambda session: kol_queries.shoot_stats_for_kols(session, kol_ids),
            lambda session: kol_enrichment.load_intel_for_npis(session, npis),
        )
    else:
        stats_by_id = await kol_queries.shoot_stats_for_kols(db, kol_ids)
        intel_by_npi = {}

    items = [
        kol_queries.to_public_kol(
            kol,
            kol.slug,
            stats_by_id.get(kol.id, kol_queries.ShootStats()),
            intel=intel_by_npi.get(kol.hcp_npi) if kol.hcp_npi and include_intel else None,
        )
        for kol in kols
    ]

    return PublicKOLList(
        items=items,
        total=facets.total,
        regions=kol_queries.build_region_facets_from_counts(facets.region_counts),
        institutions=facets.institutions,
    )


@router.get("/kols/{slug}", response_model=PublicKOL)
@limiter.limit("100/minute")
async def get_public_kol_detail(
    slug: str,
    request: Request,
    _api_key: Annotated[str, Depends(verify_public_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
    include_intel: bool = Query(default=True),
) -> PublicKOL:
    kol, resolved_slug = await kol_queries.get_kol_by_slug(db, slug)

    if kol.hcp_npi and include_intel:
        stats, intel_map = await gather_reads(
            db,
            lambda session: kol_queries.shoot_stats_for_kol(session, kol.id),
            lambda session: kol_enrichment.load_intel_for_npis(session, [kol.hcp_npi]),
        )
        intel = intel_map.get(kol.hcp_npi)
    else:
        stats = await kol_queries.shoot_stats_for_kol(db, kol.id)
        intel = None

    return kol_queries.to_public_kol(kol, resolved_slug, stats, intel=intel)


@router.get("/kols/{slug}/publications", response_model=PublicKOLPublicationList)
@limiter.limit("100/minute")
async def get_public_kol_publications(
    slug: str,
    request: Request,
    _api_key: Annotated[str, Depends(verify_public_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PublicKOLPublicationList:
    kol, _ = await kol_queries.get_kol_by_slug(db, slug)
    if not kol.hcp_npi:
        return PublicKOLPublicationList(items=[], total=0)
    return await kol_queries.list_publications(
        db, kol.hcp_npi, limit=limit, offset=offset
    )


@router.post("/hcp/upsert", response_model=HCPUpsertResponse)
@limiter.limit("100/minute")
async def post_hcp_upsert(
    payload: HCPUpsertRequest,
    request: Request,
    _api_key: Annotated[str, Depends(verify_public_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HCPUpsertResponse:
    return await hcp_upsert.upsert_hcp(db, payload)
