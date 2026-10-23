"""Daily social metrics sync (CPR-15).

YouTube: one source-wide sync stores every upload on the CHM channels in
``posts`` with today's lifetime counts in ``post_metrics_daily``, then the
linker recomputes automatic post → campaign links. Campaign reports read
YouTube from their linked posts.

LinkedIn Ads (until it moves to posts too): for every campaign with linkedin
enabled, fetches the mapped ad campaigns and stores one snapshot per day in
campaign_platform_data. Campaigns without a campaignMap entry are logged as
unmapped and never synced account-wide. LinkedIn access tokens are renewed
from LINKEDIN_ADS_REFRESH_TOKEN when it is set; the job warns when the token
that expires first (refresh token, or the static access token without one) is
close to expiring.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.campaign import Campaign
from services import platform_data, post_links, social_posts
from services.connectors import ConnectorError, linkedin_token_expires_at
from services.connectors.linkedin_auth import linkedin_ads_access_token

log = logging.getLogger(__name__)

SCHEDULED_PLATFORMS = ("youtube", "linkedin")


@dataclass
class PlatformMetricsSyncStats:
    # campaigns .. not_enabled count LinkedIn Ads campaign syncs.
    campaigns: int = 0
    synced: int = 0
    unmapped: int = 0
    no_data: int = 0
    not_enabled: int = 0
    errors: list[str] = field(default_factory=list)
    linkedin_token_days_left: int | None = None
    linkedin_token_expiring: bool = False
    youtube: social_posts.SourceSyncStats | None = None
    links: post_links.RelinkStats | None = None


async def sync_platform_metrics(
    db: AsyncSession,
    *,
    campaign_ids: list[int] | None = None,
    platforms: list[str] | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> PlatformMetricsSyncStats:
    stats = PlatformMetricsSyncStats()
    wanted = [p for p in (platforms or SCHEDULED_PLATFORMS) if p in SCHEDULED_PLATFORMS]

    if "youtube" in wanted and not dry_run:
        stats.youtube = await social_posts.sync_youtube(db, trigger="schedule", now=now)
        if stats.youtube.error:
            stats.errors.append(f"youtube: {stats.youtube.error}")
        await db.commit()
    if not dry_run:
        stats.links = await post_links.relink(db, now=now)
        await db.commit()

    query = select(Campaign).order_by(Campaign.id)
    if campaign_ids:
        query = query.where(Campaign.id.in_(campaign_ids))
    campaigns = [
        campaign
        for campaign in (await db.execute(query)).scalars()
        if "linkedin" in wanted and "linkedin" in (campaign.platforms or [])
    ]

    for campaign in campaigns:
        stats.campaigns += 1
        if dry_run:
            continue
        outcome = await platform_data.run_platform_sync(
            db, campaign, "linkedin", trigger="schedule"
        )
        await db.commit()
        if outcome.status == "ok":
            stats.synced += 1
        elif outcome.status == "unmapped":
            stats.unmapped += 1
        elif outcome.status == "no_data":
            stats.no_data += 1
        elif outcome.status == "not_enabled":
            stats.not_enabled += 1
        else:
            stats.errors.append(f"campaign {campaign.id} linkedin: {outcome.detail}")

    if "linkedin" in wanted and not dry_run:
        await _check_linkedin_token(db, stats, now or datetime.now(timezone.utc))
    if stats.errors:
        # A CloudWatch metric filter alarms on this line (platform_metrics_sync.tf).
        log.warning("platform_metrics_sync_errors count=%s first=%s", len(stats.errors), stats.errors[0])
    return stats


async def _check_linkedin_token(
    db: AsyncSession, stats: PlatformMetricsSyncStats, now: datetime
) -> None:
    """Warn ahead of the LinkedIn token that will expire first.

    With a refresh token that is the refresh token (about a year); otherwise
    the static access token (about 60 days).
    """
    settings = get_settings()
    config = await platform_data._integration_config(db, "linkedin") or {}
    try:
        token, refreshed = await linkedin_ads_access_token(settings, config)
        if refreshed is not None:
            kind, expires_at = "refresh", refreshed.refresh_expires_at
        elif token:
            kind = "access"
            expires_at = await linkedin_token_expires_at(
                access_token=token,
                client_id=settings.linkedin_ads_client_id,
                client_secret=settings.linkedin_ads_client_secret,
            )
        else:
            return
    except ConnectorError as exc:
        stats.linkedin_token_expiring = True
        log.warning("linkedin_ads_token_check_failed: %s", exc)
        return
    if expires_at is None:
        log.info("linkedin_ads_token_expiry_unknown kind=%s", kind)
        return

    days_left = (expires_at - now).days
    stats.linkedin_token_days_left = days_left
    if days_left <= settings.linkedin_ads_token_warn_days:
        stats.linkedin_token_expiring = True
        log.warning(
            "linkedin_ads_token_expiring kind=%s days_left=%s expires_at=%s",
            kind,
            days_left,
            expires_at.isoformat(),
        )
