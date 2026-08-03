"""Public WordPress editorial pass-through — `/api/public/wordpress*`.

Serves the current editorial state of communityhealth.media from Layer 2
projected-state tables (wordpress_posts + wordpress_series +
wordpress_categories + wordpress_tags + M:M association tables).

Read endpoints never touch the Layer 1 event log (`wordpress_events`) —
that's for audit + replay only. Layer 2 is rebuildable from Layer 1 at
any time, so read paths trust it as canonical.

Pass-through only for content: WordPress structure is authoritative.
Category / tag / series slugs are verbatim from WP. No ContentHub-side
tagging, curation, or ordering logic is applied.

Endpoints:
- GET /api/public/wordpress            — list current posts
- GET /api/public/wordpress/categories — distinct category terms + post counts
- GET /api/public/wordpress/tags       — distinct tag terms + post counts
- GET /api/public/wordpress/series     — distinct series terms + post counts
- GET /api/public/wordpress/series/{slug} — series detail + member post IDs
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.wordpress_projection import (
    WordPressCategory,
    WordPressPost,
    WordPressPostCategory,
    WordPressPostSeries,
    WordPressPostTag,
    WordPressSeries,
    WordPressSeriesSlugAlias,
    WordPressTag,
)
from public.deps import verify_public_api_key
from public.limits import limiter
from schemas.public import (
    PublicWordPressCategory,
    PublicWordPressCategoryList,
    PublicWordPressPost,
    PublicWordPressPostList,
    PublicWordPressSeriesDetail,
    PublicWordPressTerm,
    PublicWordPressTermList,
)


router = APIRouter(prefix="/api/public/wordpress", tags=["public-wordpress"])


# ─────────────────────────────────────────────────────────────────────────────
# Post list — Layer 2 wordpress_posts + M:M joins for filters
# ─────────────────────────────────────────────────────────────────────────────


@router.get("", response_model=PublicWordPressPostList)
@limiter.limit("100/minute")
async def get_wordpress_posts(
    request: Request,
    response: Response,
    _api_key: Annotated[str, Depends(verify_public_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
    category: Optional[str] = Query(
        None,
        description="Filter to posts that include this WordPress category slug (verbatim match)",
    ),
    tag: Optional[str] = Query(
        None,
        description="Filter to posts that include this WordPress tag slug (verbatim match)",
    ),
    series: Optional[str] = Query(
        None,
        description="Filter to posts that include this WordPress series slug (verbatim match)",
    ),
    has_youtube: bool = Query(
        False,
        description="If true, only return posts with an extracted YouTube video ID",
    ),
    since: Optional[datetime] = Query(
        None,
        description="ISO-8601 timestamp — only return posts modified at or after this time",
    ),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> PublicWordPressPostList:
    """Current editorial state of WordPress posts.

    Backed by Layer 2 `wordpress_posts` (one row per post_id, tombstoned
    via `deleted_at IS NOT NULL`). Deleted posts filtered out at query
    time. WordPress structure is authoritative — no ContentHub-side
    tagging or reordering.

    Ordered by `modified_gmt` descending (most recently edited first).
    `X-Total-Count` header reflects the total after filters, before
    pagination.
    """
    stmt = select(WordPressPost).where(WordPressPost.deleted_at.is_(None))

    if category:
        stmt = stmt.where(
            WordPressPost.post_id.in_(
                select(WordPressPostCategory.post_id).where(
                    WordPressPostCategory.category_slug == category
                )
            )
        )
    if tag:
        stmt = stmt.where(
            WordPressPost.post_id.in_(
                select(WordPressPostTag.post_id).where(
                    WordPressPostTag.tag_slug == tag
                )
            )
        )
    if series:
        stmt = stmt.where(
            WordPressPost.post_id.in_(
                select(WordPressPostSeries.post_id).where(
                    WordPressPostSeries.series_slug == series
                )
            )
        )
    if has_youtube:
        stmt = stmt.where(WordPressPost.youtube_video_id.is_not(None))
    if since:
        stmt = stmt.where(WordPressPost.modified_gmt >= since)

    # Total count before pagination.
    total = (
        await db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
    ).scalar_one()

    stmt = stmt.order_by(WordPressPost.modified_gmt.desc())
    stmt = stmt.limit(limit).offset(offset)
    rows = list((await db.execute(stmt)).scalars())

    # For each returned post, fetch its current M:M memberships in one
    # batched query per taxonomy. Keeps response N=~200 max under ~4 queries.
    post_ids = [r.post_id for r in rows]
    categories_by_post = await _fetch_memberships(
        db,
        WordPressPostCategory,
        "category_slug",
        post_ids,
    )
    tags_by_post = await _fetch_memberships(
        db,
        WordPressPostTag,
        "tag_slug",
        post_ids,
    )
    series_by_post = await _fetch_memberships(
        db,
        WordPressPostSeries,
        "series_slug",
        post_ids,
    )

    response.headers["X-Total-Count"] = str(total)

    return PublicWordPressPostList(
        items=[
            PublicWordPressPost(
                post_id=r.post_id,
                slug=r.slug,
                title=r.title,
                permalink=r.permalink,
                categories=sorted(categories_by_post.get(r.post_id, [])),
                tags=sorted(tags_by_post.get(r.post_id, [])),
                series=sorted(series_by_post.get(r.post_id, [])),
                youtube_video_id=r.youtube_video_id,
                featured_media_url=r.featured_media_url,
                modified_gmt=r.modified_gmt,
            )
            for r in rows
        ],
        total=total,
    )


async def _fetch_memberships(
    db: AsyncSession,
    assoc_model,
    slug_column: str,
    post_ids: list[int],
) -> dict[int, list[str]]:
    """Return {post_id: [slug, slug, ...]} for one taxonomy in one query."""
    if not post_ids:
        return {}
    rows = (
        await db.execute(
            select(
                assoc_model.post_id, getattr(assoc_model, slug_column)
            ).where(assoc_model.post_id.in_(post_ids))
        )
    ).all()
    by_post: dict[int, list[str]] = {}
    for post_id, slug in rows:
        by_post.setdefault(post_id, []).append(slug)
    return by_post


# ─────────────────────────────────────────────────────────────────────────────
# Categories list — Layer 2 wordpress_categories + counts
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/categories", response_model=PublicWordPressCategoryList)
@limiter.limit("100/minute")
async def get_wordpress_categories(
    request: Request,
    _api_key: Annotated[str, Depends(verify_public_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PublicWordPressCategoryList:
    """Distinct WordPress category terms with post counts.

    Backed by Layer 2 `wordpress_categories` joined against
    `wordpress_post_categories` for counts. Deleted terms excluded.

    Counts include only non-deleted posts (via subquery on wordpress_posts).

    Ordered by count descending, then slug ascending.
    """
    live_post_subq = (
        select(WordPressPost.post_id)
        .where(WordPressPost.deleted_at.is_(None))
        .subquery()
    )

    stmt = (
        select(
            WordPressCategory.slug,
            func.count(WordPressPostCategory.post_id).label("post_count"),
        )
        .outerjoin(
            WordPressPostCategory,
            (
                WordPressPostCategory.category_slug == WordPressCategory.slug
            )
            & (
                WordPressPostCategory.post_id.in_(select(live_post_subq))
            ),
        )
        .where(WordPressCategory.deleted_at.is_(None))
        .group_by(WordPressCategory.slug)
        .order_by(
            func.count(WordPressPostCategory.post_id).desc(),
            WordPressCategory.slug.asc(),
        )
    )

    rows = (await db.execute(stmt)).all()
    items = [
        PublicWordPressCategory(slug=slug, post_count=count)
        for slug, count in rows
        if count > 0  # Preserve Round 1 semantics: don't return empty categories.
    ]
    return PublicWordPressCategoryList(items=items, total=len(items))


# ─────────────────────────────────────────────────────────────────────────────
# Tags list — same shape as categories
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/tags", response_model=PublicWordPressTermList)
@limiter.limit("100/minute")
async def get_wordpress_tags(
    request: Request,
    _api_key: Annotated[str, Depends(verify_public_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PublicWordPressTermList:
    """Distinct WordPress tag terms with post counts.

    Backed by Layer 2 `wordpress_tags` + `wordpress_post_tags`. Deleted
    terms excluded. Empty tags (zero live posts) excluded.

    Each row includes `namespaced_tag` — the projection via
    wp_tag_namespace_map (WPR-11), falling back to inline rulebook
    then to `wp:<slug>`. CHT can consume either the raw slug or the
    namespaced form depending on the filter surface.

    Ordered by count descending, then slug ascending.
    """
    from jobs.wp_tag_namespace_resolver import resolve_wp_tags_batch

    base = await _list_terms(
        db,
        term_model=WordPressTag,
        assoc_model=WordPressPostTag,
        slug_column="tag_slug",
    )

    # Enrich each item with its namespaced projection.
    resolutions = await resolve_wp_tags_batch(db, [i.slug for i in base.items])
    for item in base.items:
        resolved = resolutions.get(item.slug)
        if resolved is not None:
            item.namespaced_tag = resolved.as_qualified()

    return base


# ─────────────────────────────────────────────────────────────────────────────
# Series list + detail — new endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/series", response_model=PublicWordPressTermList)
@limiter.limit("100/minute")
async def get_wordpress_series_list(
    request: Request,
    _api_key: Annotated[str, Depends(verify_public_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PublicWordPressTermList:
    """Distinct WordPress series terms with post counts.

    Backed by Layer 2 `wordpress_series` + `wordpress_post_series`. Deleted
    terms excluded. Empty series (zero live posts) excluded.

    Ordered by count descending, then slug ascending.
    """
    return await _list_terms(
        db,
        term_model=WordPressSeries,
        assoc_model=WordPressPostSeries,
        slug_column="series_slug",
    )


@router.get(
    "/series/{slug}",
    response_model=PublicWordPressSeriesDetail,
    responses={
        404: {"description": "Series not found or deleted"},
        301: {"description": "Series slug has been renamed — redirect to current slug"},
    },
)
@limiter.limit("100/minute")
async def get_wordpress_series_detail(
    request: Request,
    slug: str,
    _api_key: Annotated[str, Depends(verify_public_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PublicWordPressSeriesDetail:
    """Full detail for one series — metadata + all live member post IDs.

    Alias resolution: if `slug` matches a row in `wordpress_series_slug_alias`
    (i.e., an old slug that got renamed), returns 301 to the current slug.
    CHT can render a redirect, or its HTTP client can follow-redirects.

    Returns 404 if the slug is unknown to both the series table and the
    alias table, or if the series is tombstoned. Member post IDs exclude
    deleted posts.
    """
    term = (
        await db.execute(
            select(WordPressSeries)
            .where(WordPressSeries.slug == slug)
            .where(WordPressSeries.deleted_at.is_(None))
        )
    ).scalar_one_or_none()

    if term is None:
        # Try alias resolution — if this slug is a rename origin, 301 to the
        # current one. RedirectResponse carries Location correctly through
        # FastAPI's response pipeline (HTTPException(headers=...) doesn't
        # propagate on non-401/403 codes).
        alias = (
            await db.execute(
                select(WordPressSeriesSlugAlias).where(
                    WordPressSeriesSlugAlias.old_slug == slug
                )
            )
        ).scalar_one_or_none()
        if alias is not None:
            return RedirectResponse(
                url=f"/api/public/wordpress/series/{alias.current_slug}",
                status_code=301,
            )
        raise HTTPException(status_code=404, detail=f"Series not found: {slug}")

    post_ids = list(
        (
            await db.execute(
                select(WordPressPostSeries.post_id)
                .join(
                    WordPressPost,
                    WordPressPost.post_id == WordPressPostSeries.post_id,
                )
                .where(WordPressPostSeries.series_slug == term.slug)
                .where(WordPressPost.deleted_at.is_(None))
                .order_by(WordPressPost.modified_gmt.desc())
            )
        ).scalars()
    )

    return PublicWordPressSeriesDetail(
        slug=term.slug,
        name=term.name,
        description=term.description,
        parent_slug=term.parent_slug,
        wp_term_id=term.wp_term_id,
        post_count=len(post_ids),
        post_ids=post_ids,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Shared term-list helper (used by /tags and /series)
# ─────────────────────────────────────────────────────────────────────────────


async def _list_terms(
    db: AsyncSession,
    *,
    term_model,
    assoc_model,
    slug_column: str,
) -> PublicWordPressTermList:
    """Reusable term-list query — returns non-deleted terms with live counts."""
    live_post_subq = (
        select(WordPressPost.post_id)
        .where(WordPressPost.deleted_at.is_(None))
        .subquery()
    )

    slug_attr = getattr(assoc_model, slug_column)

    stmt = (
        select(
            term_model,
            func.count(assoc_model.post_id).label("post_count"),
        )
        .outerjoin(
            assoc_model,
            (slug_attr == term_model.slug)
            & (assoc_model.post_id.in_(select(live_post_subq))),
        )
        .where(term_model.deleted_at.is_(None))
        .group_by(term_model.slug)
        .order_by(
            func.count(assoc_model.post_id).desc(),
            term_model.slug.asc(),
        )
    )

    rows = (await db.execute(stmt)).all()

    items = [
        PublicWordPressTerm(
            slug=term.slug,
            name=term.name,
            description=term.description,
            parent_slug=term.parent_slug,
            wp_term_id=term.wp_term_id,
            post_count=count,
        )
        for term, count in rows
        if count > 0
    ]
    return PublicWordPressTermList(items=items, total=len(items))
