"""KOLs attached to a campaign by an admin (CPR-45)."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.campaign import Campaign, CampaignKOL
from models.kol import KOL
from schemas.campaigns import CampaignKolListOut, CampaignKolOut


async def list_campaign_kols(db: AsyncSession, campaign_id: int) -> CampaignKolListOut:
    await _require_campaign(db, campaign_id)
    rows = (
        await db.execute(
            select(KOL)
            .join(CampaignKOL, CampaignKOL.kol_id == KOL.id)
            .where(CampaignKOL.campaign_id == campaign_id)
            .order_by(KOL.name.asc())
        )
    ).scalars()
    return CampaignKolListOut(
        items=[
            CampaignKolOut(
                id=kol.id,
                slug=kol.slug,
                name=kol.name,
                title=kol.title,
                institution=kol.institution,
            )
            for kol in rows
        ]
    )


async def set_campaign_kols(
    db: AsyncSession, campaign_id: int, kol_ids: list[str]
) -> CampaignKolListOut:
    """Replace the attached KOLs. Unknown KOL ids are rejected (422)."""
    await _require_campaign(db, campaign_id)
    wanted = list(dict.fromkeys(kid.strip() for kid in kol_ids if kid.strip()))
    if wanted:
        found = set(
            (await db.execute(select(KOL.id).where(KOL.id.in_(wanted)))).scalars()
        )
        unknown = [kid for kid in wanted if kid not in found]
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unknown KOL ids: {', '.join(unknown)}")

    await db.execute(delete(CampaignKOL).where(CampaignKOL.campaign_id == campaign_id))
    db.add_all(CampaignKOL(campaign_id=campaign_id, kol_id=kid) for kid in wanted)
    await db.commit()
    return await list_campaign_kols(db, campaign_id)


async def _require_campaign(db: AsyncSession, campaign_id: int) -> None:
    if await db.get(Campaign, campaign_id) is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
