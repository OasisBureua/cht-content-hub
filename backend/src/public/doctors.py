"""Public /api/public/doctors endpoint — mediahub-parity port.

Returns a list of distinct doctor slugs derived from `doctor:<slug>` tags on
official-channel clips. CHT frontend consumes `slug` only (VideosPage filter
dropdown); mediahub's `shoot_count`, `post_count`, `total_views`, `total_likes`
fields are typed but never read.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.clip import Clip
from public.deps import verify_public_api_key
from public.limits import limiter
from schemas.public import PublicDoctor


router = APIRouter(prefix="/api/public", tags=["public-doctors"])


@router.get("/doctors", response_model=list[PublicDoctor])
@limiter.limit("100/minute")
async def get_doctors(
    request: Request,
    _api_key: Annotated[str, Depends(verify_public_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[PublicDoctor]:
    """Distinct doctor slugs across official-channel clips."""
    rows = list(
        (await db.execute(select(Clip.tags).where(Clip.channel == "chm-official"))).scalars()
    )
    slugs: set[str] = set()
    for tag_list in rows:
        for tag in tag_list or []:
            if tag.startswith("doctor:"):
                slugs.add(tag.split(":", 1)[1])

    return [PublicDoctor(slug=s) for s in sorted(slugs)]
