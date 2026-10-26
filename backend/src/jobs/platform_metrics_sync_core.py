"""Daily social metrics sync (CPR-15).

One source-wide sync per platform, then the linker:

- YouTube: every upload on the CHM channels in ``posts`` with today's
  lifetime counts in ``post_metrics_daily``.
- LinkedIn Ads: every creative in the ad account as a post pointing to the
  organic post it promotes, with daily metrics for the last few days (six
  months on the first run).
- The linker recomputes automatic post → campaign links. Campaign reports
  read both platforms from their linked posts.

LinkedIn access tokens are renewed from LINKEDIN_ADS_REFRESH_TOKEN; the job
warns when the token that expires first (refresh token, or the static access
token without one) is close to expiring.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from services import platform_data, post_links, social_posts
from services.connectors import ConnectorError, linkedin_token_expires_at
from services.connectors.linkedin_auth import linkedin_ads_access_token

log = logging.getLogger(__name__)

SCHEDULED_PLATFORMS = ("youtube", "linkedin")


@dataclass
class PlatformMetricsSyncStats:
    errors: list[str] = field(default_factory=list)
    youtube: social_posts.SourceSyncStats | None = None
    linkedin: social_posts.SourceSyncStats | None = None
    links: post_links.RelinkStats | None = None
    linkedin_token_days_left: int | None = None
    linkedin_token_expiring: bool = False


async def sync_platform_metrics(
    db: AsyncSession,
    *,
    platforms: list[str] | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> PlatformMetricsSyncStats:
    stats = PlatformMetricsSyncStats()
    wanted = [p for p in (platforms or SCHEDULED_PLATFORMS) if p in SCHEDULED_PLATFORMS]
    if dry_run:
        return stats

    syncs = {"youtube": social_posts.sync_youtube, "linkedin": social_posts.sync_linkedin_ads}
    for platform in wanted:
        result = await syncs[platform](db, trigger="schedule", now=now)
        setattr(stats, platform, result)
        if result.error:
            stats.errors.append(f"{platform}: {result.error}")
        await db.commit()

    stats.links = await post_links.relink(db, now=now)
    await db.commit()

    if "linkedin" in wanted:
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
