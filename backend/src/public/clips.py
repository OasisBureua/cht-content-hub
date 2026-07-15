"""Public /api/public/clips endpoint — mediahub-parity port.

Contract mirrors mediahub `backend/routers/public_api.py::get_clips` exactly,
so CHT can flip its DNS from mediahub to contenthub with zero contract change.

Only official CHM content (`clips.channel = 'chm-official'`) is exposed.
Engagement counts (`view_count`, `like_count`, `comment_count`) are aggregated
from linked posts at request time (no denormalized cache — matches mediahub).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import String as SAString, cast, func, or_, select
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.clip import Clip
from models.post import Post
from models.shoot import Shoot
from models.wordpress_event import WordPressEvent
from public.deps import verify_public_api_key
from public.limits import limiter
from schemas.public import PublicClip


router = APIRouter(prefix="/api/public", tags=["public-clips"])


_DATETIME_MIN = datetime.min.replace(tzinfo=timezone.utc)
_PLATFORM_RANK = {"youtube": 0, "podcast": 1}


def _extract_doctors(tags: list[str] | None) -> list[str]:
    if not tags:
        return []
    return [t.split(":", 1)[1] for t in tags if t.startswith("doctor:")]


def _youtube_url(provider_post_id: str | None, is_short: bool | None) -> str | None:
    if not provider_post_id:
        return None
    if is_short:
        return f"https://www.youtube.com/shorts/{provider_post_id}"
    return f"https://www.youtube.com/watch?v={provider_post_id}"


@router.get("/clips", response_model=list[PublicClip])
@limiter.limit("100/minute")
async def get_clips(
    request: Request,
    response: Response,
    _api_key: Annotated[str, Depends(verify_public_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: Optional[str] = Query(None, description="Search title, description, or tags"),
    tag: Optional[str] = Query(
        None, description="Filter by tags (comma-separated, AND logic)"
    ),
    platform: Optional[str] = None,
    doctor: Optional[str] = Query(None, description="Filter by doctor name"),
    sort_by: str = Query(
        "views",
        pattern="^(views|likes|recent|posted|recorded_at)$",
        description=(
            "Sort dimension. 'views'/'likes' = engagement totals. "
            "'recent' and 'posted' both sort by Post.posted_at (when content went "
            "up on social). 'recorded_at' sorts by Shoot.shoot_date (when content "
            "was actually recorded), falling back to posted_at for clips w/ no shoot."
        ),
    ),
    dedup_by: Optional[str] = Query(
        None,
        pattern="^(shoot)$",
        description=(
            "'shoot': collapse multiple clips per shoot_id to one canonical entry. "
            "Priority: YouTube long-form > podcast > other. shoot_id=NULL passes "
            "through unchanged."
        ),
    ),
    per_shoot_cap: int = Query(
        0,
        ge=0,
        description=(
            "After optional dedup, additionally cap the response to at most N clips "
            "per shoot_id. 0 = no cap. No effect when dedup_by=shoot."
        ),
    ),
    has_wordpress: bool = Query(
        False,
        description=(
            "If true, restrict results to clips whose YouTube video ID matches a "
            "current (non-deleted) WordPress post in `wordpress_events`. This is "
            "the editorial-catalog filter: shows only clips that are also live on "
            "communityhealth.media."
        ),
    ),
    wp_category: Optional[str] = Query(
        None,
        description=(
            "Only clips whose matching WordPress post has this category slug "
            "(verbatim, case-sensitive). Implies has_wordpress=true."
        ),
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[PublicClip]:
    """Search official CHM channel clips w/ engagement stats. Tags use AND logic.

    Only returns official CHM channel content (not branded/contractor clips).
    """
    dialect_name = db.bind.dialect.name if db.bind else "postgresql"
    is_pg = dialect_name == "postgresql"

    # Wrap tag-array containment in a dialect-aware helper.
    # Postgres: cast StringArray → text[] for `.any(...)`. SQLite: filter in Python later.
    def _tag_any(value: str):
        return cast(Clip.tags, PG_ARRAY(SAString)).any(value)

    query = select(Clip).where(Clip.channel == "chm-official")

    # WordPress editorial filter. Restrict to clips whose YouTube video ID
    # matches a current (non-deleted) `wordpress_events` row. A wp_category
    # value implies has_wordpress=true.
    #
    # Join key: extract the third `:`-separated segment of clip.id
    # (`official:youtube:<youtube_video_id>`) and match against
    # wordpress_events.youtube_video_id. Only Postgres supports the
    # split_part function; on SQLite (tests) we filter in Python later.
    filter_by_wp = has_wordpress or bool(wp_category)
    if filter_by_wp and is_pg:
        # Latest non-deleted event per post_id
        wp_latest = (
            select(WordPressEvent)
            .where(WordPressEvent.event != "deleted")
            .distinct(WordPressEvent.post_id)
            .order_by(
                WordPressEvent.post_id,
                WordPressEvent.modified_gmt.desc(),
                WordPressEvent.id.desc(),
            )
            .subquery()
        )
        clip_yt_id = func.split_part(Clip.id, ":", 3)
        query = query.join(
            wp_latest, clip_yt_id == wp_latest.c.youtube_video_id
        )
        if wp_category:
            query = query.where(
                cast(wp_latest.c.categories, PG_JSONB).contains(
                    cast([wp_category], PG_JSONB)
                )
            )

    # `q` and tag filters both need array membership on postgres.
    tags_list: list[str] = (
        [t.strip() for t in tag.split(",") if t.strip()] if tag else []
    )
    doctor_tag = f"doctor:{doctor}" if doctor else None

    if is_pg:
        if q:
            search_term = f"%{q}%"
            query = query.where(
                or_(
                    Clip.title.ilike(search_term),
                    Clip.description.ilike(search_term),
                    _tag_any(q),
                )
            )
        for t in tags_list:
            query = query.where(_tag_any(t))
        if doctor_tag:
            query = query.where(_tag_any(doctor_tag))
    else:
        # SQLite path (tests only): fallback to text search + Python-side tag filter.
        if q:
            search_term = f"%{q}%"
            query = query.where(
                or_(
                    Clip.title.ilike(search_term),
                    Clip.description.ilike(search_term),
                )
            )

    if platform:
        query = query.where(Clip.platform == platform)

    clips = list((await db.execute(query)).scalars())

    if not is_pg and filter_by_wp:
        # SQLite (tests) path: fetch current WP editorial state, filter in Python.
        wp_rows = list((await db.execute(select(WordPressEvent))).scalars())
        # Latest-per-post_id (by received_at), excluding deleted
        latest_by_post: dict[int, WordPressEvent] = {}
        for row in wp_rows:
            existing = latest_by_post.get(row.post_id)
            if existing is None or row.received_at > existing.received_at:
                latest_by_post[row.post_id] = row
        active = [r for r in latest_by_post.values() if r.event != "deleted"]
        allowed_youtube_ids: set[str] = set()
        for r in active:
            if not r.youtube_video_id:
                continue
            if wp_category and wp_category not in (r.categories or []):
                continue
            allowed_youtube_ids.add(r.youtube_video_id)

        def _wp_matches(clip: Clip) -> bool:
            parts = (clip.id or "").split(":")
            if len(parts) < 3 or not parts[2]:
                return False
            return parts[2] in allowed_youtube_ids

        clips = [c for c in clips if _wp_matches(c)]

    if not is_pg and (tags_list or doctor_tag or q):
        def _has_all(clip: Clip) -> bool:
            ctags = clip.tags or []
            if tags_list and not all(t in ctags for t in tags_list):
                return False
            if doctor_tag and doctor_tag not in ctags:
                return False
            # For q, also allow exact tag match (Postgres path does this via or_)
            if q and q not in ctags and not (
                (clip.title and q.lower() in clip.title.lower())
                or (clip.description and q.lower() in clip.description.lower())
            ):
                return False
            return True

        clips = [c for c in clips if _has_all(c)]
    if not clips:
        response.headers["X-Total-Count"] = "0"
        return []

    clip_ids = [c.id for c in clips]
    posts = list(
        (await db.execute(select(Post).where(Post.clip_id.in_(clip_ids)))).scalars()
    )
    posts_by_clip: dict[str, list[Post]] = {}
    for post in posts:
        if post.clip_id:
            posts_by_clip.setdefault(post.clip_id, []).append(post)

    shoot_ids = list({c.shoot_id for c in clips if c.shoot_id})
    shoot_names: dict[str, str] = {}
    shoot_dates: dict[str, datetime] = {}
    if shoot_ids:
        shoots_result = await db.execute(
            select(Shoot.id, Shoot.name, Shoot.shoot_date).where(
                Shoot.id.in_(shoot_ids)
            )
        )
        for row in shoots_result:
            shoot_names[row.id] = row.name
            if row.shoot_date:
                shoot_dates[row.id] = row.shoot_date

    enriched: list[dict] = []
    for clip in clips:
        clip_posts = posts_by_clip.get(clip.id, [])
        total_views = sum(p.view_count for p in clip_posts)
        total_likes = sum(p.like_count for p in clip_posts)
        total_comments = sum(p.comment_count for p in clip_posts)

        yt_url = None
        yt_thumbnail = None
        posted_at: Optional[datetime] = None
        is_short = clip.is_short
        for post in clip_posts:
            if post.platform == "youtube" and post.provider_post_id:
                yt_url = _youtube_url(post.provider_post_id, is_short)
                yt_thumbnail = post.thumbnail_url
                if not posted_at or (post.posted_at and post.posted_at > posted_at):
                    posted_at = post.posted_at
            if not posted_at and post.posted_at:
                posted_at = post.posted_at

        recorded_at = (
            shoot_dates.get(clip.shoot_id) if clip.shoot_id else None
        ) or (posted_at or clip.earliest_posted_at)

        enriched.append(
            {
                "clip": clip,
                "total_views": total_views,
                "total_likes": total_likes,
                "total_comments": total_comments,
                "youtube_url": yt_url,
                "thumbnail_url": yt_thumbnail or clip.video_preview_url,
                "posted_at": posted_at or clip.earliest_posted_at,
                "recorded_at": recorded_at,
                "is_short": is_short,
            }
        )

    if sort_by == "views":
        enriched.sort(key=lambda x: x["total_views"], reverse=True)
    elif sort_by == "likes":
        enriched.sort(key=lambda x: x["total_likes"], reverse=True)
    elif sort_by in ("recent", "posted"):
        enriched.sort(key=lambda x: x["posted_at"] or _DATETIME_MIN, reverse=True)
    elif sort_by == "recorded_at":
        enriched.sort(key=lambda x: x["recorded_at"] or _DATETIME_MIN, reverse=True)

    if dedup_by == "shoot":
        groups: dict[str | None, list] = defaultdict(list)
        order: list[str | None] = []
        for item in enriched:
            sid = item["clip"].shoot_id
            if sid not in groups:
                order.append(sid)
            groups[sid].append(item)
        deduped: list = []
        for sid in order:
            group = groups[sid]
            if sid is None:
                deduped.extend(group)
            else:
                best = min(
                    group,
                    key=lambda x: _PLATFORM_RANK.get(
                        (x["clip"].platform or "").lower(), 99
                    ),
                )
                deduped.append(best)
        enriched = deduped

    if per_shoot_cap > 0:
        seen_count: dict[str | None, int] = defaultdict(int)
        capped: list = []
        for item in enriched:
            sid = item["clip"].shoot_id
            if sid is None:
                capped.append(item)
                continue
            if seen_count[sid] < per_shoot_cap:
                seen_count[sid] += 1
                capped.append(item)
        enriched = capped

    response.headers["X-Total-Count"] = str(len(enriched))
    page = enriched[offset : offset + limit]

    return [
        PublicClip(
            id=item["clip"].id,
            title=item["clip"].title,
            description=item["clip"].description,
            ai_summary=item["clip"].ai_summary,
            tags=item["clip"].tags or [],
            doctors=_extract_doctors(item["clip"].tags),
            thumbnail_url=item["thumbnail_url"],
            youtube_url=item["youtube_url"],
            duration_seconds=item["clip"].duration_seconds,
            is_short=item["is_short"],
            posted_at=item["posted_at"],
            view_count=item["total_views"],
            like_count=item["total_likes"],
            comment_count=item["total_comments"],
            shoot_id=item["clip"].shoot_id,
            shoot_name=shoot_names.get(item["clip"].shoot_id) if item["clip"].shoot_id else None,
        )
        for item in page
    ]


@router.get("/clips/{clip_id}", response_model=PublicClip)
@limiter.limit("100/minute")
async def get_clip_detail(
    clip_id: str,
    request: Request,
    _api_key: Annotated[str, Depends(verify_public_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PublicClip:
    """Single official CHM clip with enrichment. Mirrors mediahub /api/public/clips/{id}."""
    clip = (
        await db.execute(
            select(Clip).where(Clip.id == clip_id, Clip.channel == "chm-official")
        )
    ).scalar_one_or_none()
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")

    posts = list(
        (await db.execute(select(Post).where(Post.clip_id == clip_id))).scalars()
    )
    total_views = sum(p.view_count for p in posts)
    total_likes = sum(p.like_count for p in posts)
    total_comments = sum(p.comment_count for p in posts)

    yt_url: Optional[str] = None
    yt_thumbnail: Optional[str] = None
    posted_at: Optional[datetime] = None
    for post in posts:
        if post.platform == "youtube" and post.provider_post_id:
            yt_url = _youtube_url(post.provider_post_id, clip.is_short)
            yt_thumbnail = post.thumbnail_url
        if post.posted_at and (not posted_at or post.posted_at > posted_at):
            posted_at = post.posted_at

    shoot_name: Optional[str] = None
    if clip.shoot_id:
        row = (
            await db.execute(select(Shoot.name).where(Shoot.id == clip.shoot_id))
        ).scalar_one_or_none()
        if row:
            shoot_name = row

    return PublicClip(
        id=clip.id,
        title=clip.title,
        description=clip.description,
        ai_summary=clip.ai_summary,
        tags=clip.tags or [],
        doctors=_extract_doctors(clip.tags),
        thumbnail_url=yt_thumbnail or clip.video_preview_url,
        youtube_url=yt_url,
        duration_seconds=clip.duration_seconds,
        is_short=clip.is_short,
        posted_at=posted_at or clip.earliest_posted_at,
        view_count=total_views,
        like_count=total_likes,
        comment_count=total_comments,
        shoot_id=clip.shoot_id,
        shoot_name=shoot_name,
    )
