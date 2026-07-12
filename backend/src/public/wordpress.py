"""Public WordPress editorial pass-through — `/api/public/wordpress*`.

Serves the current editorial state of communityhealth.media directly
from `wordpress_events`. Powers the CHT admin dashboard's Content tab.

Pass-through only: WordPress structure is authoritative. No ContentHub-
side tagging, curation, or ordering logic is applied — categories are
verbatim WP slugs, posts are ordered by `modified_gmt` (most recent
first), and only the latest non-deleted event per `post_id` is returned.

Endpoints:
- GET /api/public/wordpress            — list current posts
- GET /api/public/wordpress/categories — distinct category slugs + counts
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.wordpress_event import WordPressEvent
from public.deps import verify_public_api_key
from public.limits import limiter
from schemas.public import (
    PublicWordPressCategory,
    PublicWordPressCategoryList,
    PublicWordPressPost,
    PublicWordPressPostList,
)


router = APIRouter(prefix="/api/public/wordpress", tags=["public-wordpress"])


async def _latest_non_deleted_rows(db: AsyncSession) -> list[WordPressEvent]:
    """Return the latest non-deleted event per `post_id`.

    A publish → update → delete stream produces three rows in
    `wordpress_events`; the current editorial state is the most-recent
    non-deleted row per post_id. If the most-recent row IS a delete,
    the post is excluded entirely.

    Dialect-aware: Postgres uses DISTINCT ON, SQLite (tests) uses a
    correlated MAX subquery.
    """
    dialect_name = db.bind.dialect.name if db.bind else "postgresql"

    if dialect_name == "postgresql":
        # DISTINCT ON (post_id) ordered by modified_gmt desc gets one row
        # per post (the newest); then filter out delete events in Python.
        stmt = (
            select(WordPressEvent)
            .distinct(WordPressEvent.post_id)
            .order_by(
                WordPressEvent.post_id,
                WordPressEvent.modified_gmt.desc(),
                WordPressEvent.id.desc(),
            )
        )
        rows = list((await db.execute(stmt)).scalars())
    else:
        # SQLite path: correlated subquery for latest received_at per post_id.
        # Test datasets are tiny — no need to optimize further.
        subq = (
            select(
                WordPressEvent.post_id,
                func.max(WordPressEvent.received_at).label("latest"),
            )
            .group_by(WordPressEvent.post_id)
            .subquery()
        )
        stmt = (
            select(WordPressEvent)
            .join(
                subq,
                (WordPressEvent.post_id == subq.c.post_id)
                & (WordPressEvent.received_at == subq.c.latest),
            )
            .order_by(WordPressEvent.modified_gmt.desc())
        )
        rows = list((await db.execute(stmt)).scalars())

    return [r for r in rows if r.event != "deleted"]


@router.get("/categories", response_model=PublicWordPressCategoryList)
@limiter.limit("100/minute")
async def get_wordpress_categories(
    request: Request,
    _api_key: Annotated[str, Depends(verify_public_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PublicWordPressCategoryList:
    """Distinct WordPress category slugs with per-slug post counts.

    Counts reflect the current editorial state: latest non-deleted
    event per `post_id`, then category slugs unnested and counted.

    Slugs are verbatim from WordPress — no case-folding, no prefix
    normalization. Ordered by count descending, then slug ascending.
    """
    rows = await _latest_non_deleted_rows(db)

    counts: dict[str, int] = {}
    for row in rows:
        for slug in row.categories or []:
            if not slug:
                continue
            counts[slug] = counts.get(slug, 0) + 1

    items = [
        PublicWordPressCategory(slug=slug, post_count=count)
        for slug, count in sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    ]
    return PublicWordPressCategoryList(items=items, total=len(items))


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

    Coalesces the raw event stream to one row per `post_id` (latest
    non-deleted event). WordPress structure is authoritative — this
    endpoint applies no ContentHub-side tagging or reordering.

    Ordered by `modified_gmt` descending (most recently edited first).
    `X-Total-Count` header reflects the total after filters, before
    pagination.
    """
    rows = await _latest_non_deleted_rows(db)

    if category:
        rows = [r for r in rows if category in (r.categories or [])]
    if tag:
        rows = [r for r in rows if tag in (r.tags or [])]
    if has_youtube:
        rows = [r for r in rows if r.youtube_video_id]
    if since:
        # Compare as UTC-aware. wordpress_events.modified_gmt is stored
        # with tzinfo; incoming `since` from FastAPI is parsed to a
        # tz-aware datetime when the string contains an offset (or 'Z').
        rows = [r for r in rows if r.modified_gmt >= since]

    rows.sort(key=lambda r: r.modified_gmt, reverse=True)

    total = len(rows)
    page = rows[offset : offset + limit]

    response.headers["X-Total-Count"] = str(total)

    return PublicWordPressPostList(
        items=[
            PublicWordPressPost(
                post_id=r.post_id,
                slug=r.slug,
                title=r.title,
                permalink=r.permalink,
                categories=r.categories or [],
                tags=r.tags or [],
                youtube_video_id=r.youtube_video_id,
                featured_media_url=r.featured_media_url,
                modified_gmt=r.modified_gmt,
            )
            for r in page
        ],
        total=total,
    )
