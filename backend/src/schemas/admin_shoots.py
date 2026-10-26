"""Admin shoot → campaign mapping (CPR-15)."""

from __future__ import annotations

from datetime import datetime

from schemas.campaigns import ApiModel


class ShootOut(ApiModel):
    id: str
    name: str
    shoot_date: datetime | None = None
    youtube_playlist_id: str | None = None
    campaign_id: int | None = None
    post_count: int = 0


class ShootListOut(ApiModel):
    items: list[ShootOut]


class ShootCampaignUpdate(ApiModel):
    # null clears the mapping.
    campaign_id: int | None = None


class ShootCampaignOut(ApiModel):
    shoot: ShootOut
    links_created: int
    links_removed: int
