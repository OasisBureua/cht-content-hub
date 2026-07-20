"""Public KOL network + playlist API."""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.playlist_tag import PlaylistTag
from public.deps import verify_public_api_key
from public.limits import limiter
from schemas.public import (
    HCPUpsertRequest,
    HCPUpsertResponse,
    PublicKOL,
    PublicKOLList,
    PublicKOLPublicationList,
    PublicPlaylistTag,
    PublicPlaylistTagList,
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


@router.get("/playlists", response_model=PublicPlaylistTagList)
@limiter.limit("100/minute")
async def get_public_playlists(
    request: Request,
    response: Response,
    _api_key: Annotated[str, Depends(verify_public_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
    tag: Optional[str] = Query(
        None,
        description=(
            "Filter by namespaced tags (comma-separated). Semantics: AND across "
            "namespaces, OR within a namespace. Same vocabulary as clip tags: "
            "biomarker:her2-low, drug:t-dxd, etc. Example: "
            "?tag=biomarker:her2-low,biomarker:her2-ultra-low,drug:t-dxd → "
            "playlists where (biomarker in {her2-low, her2-ultra-low}) AND drug=t-dxd."
        ),
    ),
    lane: Optional[str] = Query(
        None,
        pattern="^(biomarker|drug|trial|doctor_pair|mixed|archive)$",
        description=(
            "Filter by editorial lane. "
            "Allowed values: biomarker | drug | trial | doctor_pair | mixed | archive. "
            "Use to surface 'all biomarker-lane playlists' or 'all doctor_pair playlists' "
            "without filtering on a specific tag."
        ),
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> PublicPlaylistTagList:
    """List curator-tagged YouTube playlists.

    Returns rows from the `playlist_tags` overlay table. Only playlists that
    have been explicitly tagged by a curator appear here — untagged
    YouTube playlists are not in this table. Powers CHT's biomarker-row
    queries (replaces the brittle frontend `_generated-catalog-playlists.json`
    fuzzy-title-match approach).

    The full playlist metadata (title, description, video_count) is NOT
    returned by this endpoint. Fetch it separately from the YouTube Data
    API by playlist ID, then join with these tags client-side.

    Pagination: returns up to `limit` items starting at `offset`.
    `X-Total-Count` response header reflects the unpaginated count.
    """
    query = select(PlaylistTag)

    if lane:
        query = query.where(PlaylistTag.lane == lane)

    tags_list = (
        [t.strip() for t in tag.split(",") if t.strip()] if tag else []
    )

    # Postgres path: use ARRAY .any() for efficient DB-side filtering.
    # SQLite (tests) path: no ARRAY operator support — load all matches
    # against `lane`, then filter tags in Python. Volume in prod queries
    # is capped by `limit` (max 200); test datasets are tiny.
    dialect_name = db.bind.dialect.name if db.bind else "postgresql"

    if tags_list and dialect_name == "postgresql":
        # SCRUM-77: AND across namespaces, OR within a namespace.
        from services.tag_query import postgres_tag_filter
        tag_filter = postgres_tag_filter(PlaylistTag.tags, tags_list)
        if tag_filter is not None:
            query = query.where(tag_filter)

    # Order: lane first (groups same-lane playlists), then most-recently-updated
    # so newly-curated entries surface to the top.
    query = query.order_by(PlaylistTag.lane.asc(), PlaylistTag.updated_at.desc())

    if tags_list and dialect_name != "postgresql":
        # SQLite fallback — SCRUM-77 semantics on the test path too.
        from services.tag_query import python_row_matches
        all_rows = list((await db.execute(query)).scalars())
        matching = [r for r in all_rows if python_row_matches(r.tags, tags_list)]
        total = len(matching)
        rows = matching[offset : offset + limit]
    else:
        # Count before pagination (for X-Total-Count)
        count_query = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_query)).scalar_one()

        rows = list(
            (
                await db.execute(query.limit(limit).offset(offset))
            ).scalars()
        )

    response.headers["X-Total-Count"] = str(total)

    return PublicPlaylistTagList(
        items=[
            PublicPlaylistTag(
                youtube_playlist_id=r.youtube_playlist_id,
                tags=r.tags or [],
                lane=r.lane,
            )
            for r in rows
        ],
        total=total,
    )
