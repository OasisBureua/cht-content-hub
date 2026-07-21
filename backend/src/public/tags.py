"""Public /api/public/tags endpoint.

Returns `{namespace: [tag_value, ...]}` grouped by the `namespace:` prefix.

## Data sources (revised 2026-07-21)

Three sources contribute, all treated as freeform per SCRUM-73 revised
taxonomy. Everything gets grouped by namespace prefix; unprefixed values
fall under `"other"`.

1. **Clip.tags** — biomarker/drug/trial/doctor/topic/stage tags on
   chm-official clips (LLM-seeded from the mediahub migration + updated
   going forward by `admin/clip_tags` PATCH and the doctor_tagger cron)
2. **Post.tags** — same shape, applies to social posts derived from
   clips
3. **wordpress_events (latest per post)** — editorial-controlled surfaces
   projected into two namespaces:
     - `topic:*` from `categories` (WordPress categories = editorial topics)
     - `wp:*` from `tags` (WordPress post_tag taxonomy = editorial keywords)

This projection matches Sebastien's architectural intent: **editorial
teams own tag semantics**. WordPress category/tag changes surface here
immediately (subject to Redis TTL on the CHT proxy — writes trigger a
cache-clear).

Note: this endpoint does NOT return the actual tags-per-clip. That's the
`/api/public/clips` endpoint. This is just the union universe of tags
across the catalog.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.clip import Clip
from models.post import Post
from models.wordpress_event import WordPressEvent
from public.deps import verify_public_api_key
from public.limits import limiter


router = APIRouter(prefix="/api/public", tags=["public-tags"])


def _add_namespaced(grouped: dict[str, set[str]], tag: str) -> None:
    """Split `namespace:value`; put bare tags under `other`."""
    if ":" in tag:
        ns, _, value = tag.partition(":")
        ns = ns.strip()
        value = value.strip()
        if ns and value:
            grouped[ns].add(f"{ns}:{value}")
            return
    stripped = tag.strip()
    if stripped:
        grouped["other"].add(stripped)


@router.get("/tags", response_model=dict[str, list[str]])
@limiter.limit("100/minute")
async def get_tags(
    request: Request,
    _api_key: Annotated[str, Depends(verify_public_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, list[str]]:
    """Union of Clip.tags + Post.tags + WordPress editorial tags.

    Returns `{namespace: [tag_value, ...]}`. Sorted within each namespace
    for stable frontend rendering.
    """
    clip_tag_rows = list(
        (await db.execute(select(Clip.tags).where(Clip.channel == "chm-official"))).scalars()
    )
    post_tag_rows = list(
        (await db.execute(select(Post.tags))).scalars()
    )

    # WordPress editorial: one row per WP post, latest-modified only,
    # excluding deleted posts. Same pattern as `public/clips.py` wp_latest
    # subquery + `public/wordpress.py` current-state view.
    wp_latest = (
        select(WordPressEvent.categories, WordPressEvent.tags)
        .where(WordPressEvent.event != "deleted")
        .distinct(WordPressEvent.post_id)
        .order_by(
            WordPressEvent.post_id,
            WordPressEvent.modified_gmt.desc(),
            WordPressEvent.id.desc(),
        )
    )
    wp_rows = list((await db.execute(wp_latest)).all())

    grouped: dict[str, set[str]] = defaultdict(set)

    # Clip + Post tags (already namespaced, or falls to `other`).
    for tag_list in (*clip_tag_rows, *post_tag_rows):
        for tag in tag_list or []:
            if isinstance(tag, str):
                _add_namespaced(grouped, tag)

    # WordPress projection: categories → topic:, tags → wp:.
    # These are freeform editorial slugs; we prefix on the way out to
    # normalize the shape of the response.
    for cats, wp_tags in wp_rows:
        for cat in cats or []:
            if isinstance(cat, str) and cat.strip():
                grouped["topic"].add(f"topic:{cat.strip()}")
        for wp_tag in wp_tags or []:
            if isinstance(wp_tag, str) and wp_tag.strip():
                grouped["wp"].add(f"wp:{wp_tag.strip()}")

    return {ns: sorted(vals) for ns, vals in grouped.items()}
