"""Admin API for mapping shoots to campaigns (CPR-15).

- GET   /api/admin/shoots                 — shoots with their campaign and post count
- PATCH /api/admin/shoots/{id}/campaign   — set or clear the shoot's campaign

Every post from a shoot (videos in its YouTube playlist) links to the
shoot's campaign through the linker's ``shoot`` rule, so the PATCH relinks
right away. Auth: Bearer M2M with ``hub/admin.{crud}``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from admin.cache import notify_cht_cache_clear
from admin.deps import verify_admin_api_key
from database import get_db
from models.campaign import Campaign
from models.post import Post
from models.shoot import Shoot
from schemas.admin_shoots import ShootCampaignOut, ShootCampaignUpdate, ShootListOut, ShootOut
from services import post_links

router = APIRouter(prefix="/api/admin", tags=["admin-shoots"])


def _out(shoot: Shoot, post_count: int) -> ShootOut:
    return ShootOut(
        id=shoot.id,
        name=shoot.name,
        shoot_date=shoot.shoot_date,
        youtube_playlist_id=shoot.youtube_playlist_id,
        campaign_id=shoot.campaign_id,
        post_count=post_count,
    )


async def _post_counts(db: AsyncSession) -> dict[str, int]:
    return dict(
        (
            await db.execute(
                select(Post.shoot_id, func.count()).where(Post.shoot_id.is_not(None)).group_by(Post.shoot_id)
            )
        ).all()
    )


@router.get("/shoots", response_model=ShootListOut)
async def list_shoots(
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ShootListOut:
    counts = await _post_counts(db)
    shoots = (
        await db.execute(select(Shoot).order_by(Shoot.shoot_date.desc().nulls_last(), Shoot.name))
    ).scalars()
    return ShootListOut(items=[_out(shoot, counts.get(shoot.id, 0)) for shoot in shoots])


@router.patch("/shoots/{shoot_id}/campaign", response_model=ShootCampaignOut)
async def set_shoot_campaign(
    shoot_id: str,
    payload: ShootCampaignUpdate,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ShootCampaignOut:
    shoot = await db.get(Shoot, shoot_id)
    if shoot is None:
        raise HTTPException(status_code=404, detail="Shoot not found")
    if payload.campaign_id is not None and await db.get(Campaign, payload.campaign_id) is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    shoot.campaign_id = payload.campaign_id
    await db.flush()
    stats = await post_links.relink(db)
    await notify_cht_cache_clear(scope="contenthub")
    counts = await _post_counts(db)
    return ShootCampaignOut(
        shoot=_out(shoot, counts.get(shoot.id, 0)),
        links_created=stats.created + stats.reactivated,
        links_removed=stats.removed,
    )
