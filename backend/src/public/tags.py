"""Public /api/public/tags endpoint — mediahub-parity port.

Returns `{namespace: [tag_slug, ...]}` grouped by the `namespace:` prefix on
Clip.tags and Post.tags. CHT frontend consumes:

- Dashboard iterates all keys (no filter)
- ExploreOpportunities only checks `Object.keys(tags).length > 0`
- VideosPage reads six specific namespaces: biomarker, stage, drug, trial, topic, brand

Values are returned with the namespace prefix intact (e.g. `biomarker:HER2+`);
frontend strips the prefix client-side.

MVP note: mediahub's endpoint reclassifies bare (unprefixed) tags via
`tag_vocabulary` and dumps unresolved into `"other"`. ContentHub has no
TagVocabulary model, so bare tags fall under `"other"` unconditionally.
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
from public.deps import verify_public_api_key
from public.limits import limiter


router = APIRouter(prefix="/api/public", tags=["public-tags"])


@router.get("/tags", response_model=dict[str, list[str]])
@limiter.limit("100/minute")
async def get_tags(
    request: Request,
    _api_key: Annotated[str, Depends(verify_public_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, list[str]]:
    """Grouped tag namespace map used by CHT catalog filters."""
    clip_tag_rows = list(
        (await db.execute(select(Clip.tags).where(Clip.channel == "chm-official"))).scalars()
    )
    post_tag_rows = list(
        (await db.execute(select(Post.tags))).scalars()
    )

    grouped: dict[str, set[str]] = defaultdict(set)
    for tag_list in (*clip_tag_rows, *post_tag_rows):
        for tag in tag_list or []:
            if ":" in tag:
                ns, _ = tag.split(":", 1)
                grouped[ns].add(tag)
            else:
                grouped["other"].add(tag)

    return {ns: sorted(vals) for ns, vals in grouped.items()}
