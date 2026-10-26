"""Social posts from platform APIs, with metrics per post per day (CPR-15).

YouTube: the daily sync lists every upload on the configured channels (plus
any YouTube post the Hub already has), upserts them into ``posts``, stores
today's lifetime views / likes / comments in ``post_metrics_daily`` and keeps
the legacy count columns on ``posts`` current for the public clips API. Shoot
playlists give new uploads their ``shoot_id``.

LinkedIn Ads: every creative in the ad account becomes a post (source
``linkedin_ads``) that points to the organic post it promotes, with one
metrics row per active day. Each run re-reads the last few days, which
LinkedIn still revises; the first run backfills six months.

Campaign snapshots (``campaign_post_snapshots``) turn a campaign's linked
posts back into the per-platform rows that platform-data, the analytics
report and the report packet already read.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import OFFICIAL_YOUTUBE_CHANNEL_ID, Settings, get_settings
from models.campaign import CampaignPlatformData, IntegrationSetting, PlatformSyncRun
from models.post import Post
from models.shoot import Shoot
from models.social import (
    BASIS_DAILY,
    BASIS_LIFETIME,
    LINK_ACTIVE,
    PostCampaignLink,
    PostMetricDaily,
)
from services.connectors.common import ConnectorError, integration_or_env, metric_str, safe_rate
from services.connectors.linkedin_ads import (
    AdCampaign,
    Creative,
    fetch_creative_days,
    list_ad_campaigns,
    list_creatives,
    post_url,
)
from services.connectors.linkedin_auth import linkedin_ads_access_token
from services.connectors.youtube import (
    YouTubeVideo,
    fetch_videos,
    format_duration,
    list_playlist_video_ids,
    uploads_playlist_id,
)

log = logging.getLogger(__name__)

YOUTUBE = "youtube"
LINKEDIN = "linkedin"
POST_SOURCE_YOUTUBE = "youtube_api"
POST_SOURCE_LINKEDIN_ADS = "linkedin_ads"
# post_metrics_daily.source per platform (where the numbers came from) and
# whether rows are lifetime totals or per-day numbers.
METRICS_SOURCE = {YOUTUBE: "youtube", LINKEDIN: "linkedin_ads"}
METRICS_BASIS = {YOUTUBE: BASIS_LIFETIME, LINKEDIN: BASIS_DAILY}
# LinkedIn keeps daily ad analytics for six months.
LINKEDIN_BACKFILL_DAYS = 180


@dataclass
class SourceSyncStats:
    platform: str
    posts: int = 0
    created: int = 0
    updated: int = 0
    not_returned: int = 0
    shoot_assigned: int = 0
    promoted_found: int = 0
    metric_rows: int = 0
    error: str | None = None


def _http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=30.0)


def youtube_channel_ids(settings: Settings) -> list[str]:
    return [part.strip() for part in settings.youtube_channel_ids.split(",") if part.strip()]


def utc_today(now: datetime) -> date:
    return now.astimezone(timezone.utc).date()


async def sync_youtube(
    db: AsyncSession,
    *,
    trigger: str,
    video_ids: list[str] | None = None,
    log_run: bool = True,
    client: httpx.AsyncClient | None = None,
    now: datetime | None = None,
) -> SourceSyncStats:
    """Refresh YouTube posts and today's snapshot.

    ``video_ids=None`` is the full daily sync: every upload on the configured
    channels, every YouTube post already in the Hub, and every video in a
    shoot playlist. Otherwise only the given videos are refreshed. A platform
    failure is returned in ``error``, not raised. With ``log_run`` the
    attempt is logged as a source-wide sync run (no campaign).
    """
    now = now or datetime.now(timezone.utc)
    settings = get_settings()
    stats = SourceSyncStats(platform=YOUTUBE)

    own_client = client is None
    if own_client:
        client = _http_client()
    try:
        if not settings.youtube_api_key:
            raise ConnectorError("YouTube API key missing — set YOUTUBE_API_KEY")
        playlist_shoots: dict[str, str] = {}
        if video_ids is None:
            ids: list[str] = []
            for channel_id in youtube_channel_ids(settings):
                ids += await list_playlist_video_ids(
                    api_key=settings.youtube_api_key,
                    playlist_id=uploads_playlist_id(channel_id),
                    client=client,
                )
            # Posts already in the Hub may be unlisted, so not in uploads.
            ids += (
                await db.execute(
                    select(Post.provider_post_id).where(
                        Post.platform == YOUTUBE, Post.provider_post_id.is_not(None)
                    )
                )
            ).scalars().all()
            # Shoot playlists can hold videos that are not public uploads.
            playlist_shoots = await _shoot_playlist_videos(db, settings.youtube_api_key, client)
            ids += list(playlist_shoots)
        else:
            ids = list(video_ids)
        videos = await fetch_videos(api_key=settings.youtube_api_key, video_ids=ids, client=client)
    except ConnectorError as exc:
        return await _failed(db, stats, exc, trigger=trigger, started=now, log_run=log_run)
    finally:
        if own_client:
            await client.aclose()

    stats.posts = len(videos)
    stats.not_returned = len(set(ids)) - len(videos)
    await _store_youtube(db, videos, playlist_shoots, now=now, stats=stats)
    if log_run:
        _log_run(db, platform=YOUTUBE, trigger=trigger, started=now, error=None)
        await db.flush()
    return stats


async def _shoot_playlist_videos(
    db: AsyncSession, api_key: str, client: httpx.AsyncClient
) -> dict[str, str]:
    """video ID → shoot ID, from each shoot's YouTube playlist."""
    shoots = (
        await db.execute(
            select(Shoot.id, Shoot.youtube_playlist_id).where(Shoot.youtube_playlist_id.is_not(None))
        )
    ).all()
    by_video: dict[str, str] = {}
    for shoot_id, playlist_id in shoots:
        try:
            video_ids = await list_playlist_video_ids(
                api_key=api_key, playlist_id=playlist_id, client=client
            )
        except ConnectorError as exc:
            # A deleted or private playlist shouldn't stop the sync.
            log.warning("youtube_shoot_playlist_failed shoot=%s: %s", shoot_id, exc)
            continue
        for video_id in video_ids:
            by_video.setdefault(video_id, shoot_id)
    return by_video


async def _store_youtube(
    db: AsyncSession,
    videos: list[YouTubeVideo],
    playlist_shoots: dict[str, str],
    *,
    now: datetime,
    stats: SourceSyncStats,
) -> None:
    ids = [video.video_id for video in videos]
    posts = {
        post.provider_post_id: post
        for post in (
            await db.execute(
                select(Post).where(Post.platform == YOUTUBE, Post.provider_post_id.in_(ids))
            )
        ).scalars()
    }
    for video in videos:
        post = posts.get(video.video_id)
        if post is None:
            post = _new_post(
                platform=YOUTUBE,
                provider_post_id=video.video_id,
                source=POST_SOURCE_YOUTUBE,
                content_type="video",
                channel="chm-official" if video.channel_id == OFFICIAL_YOUTUBE_CHANNEL_ID else None,
            )
            db.add(post)
            posts[video.video_id] = post
            stats.created += 1
        else:
            stats.updated += 1
        post.title = video.title[:500]
        post.description = video.description
        post.posted_at = video.published_at
        post.thumbnail_url = video.thumbnail_url
        post.content_url = video.url
        post.duration_seconds = video.duration_seconds
        post.provider_account_id = video.channel_id
        post.platform_metadata = {
            **(post.platform_metadata or {}),
            "channelTitle": video.channel_title,
            "liveBroadcastContent": video.live_broadcast,
        }
        post.view_count = video.views
        post.like_count = video.likes
        post.comment_count = video.comments
        post.stats_synced_at = now
        shoot_id = playlist_shoots.get(video.video_id)
        if shoot_id and post.shoot_id is None:
            post.shoot_id = shoot_id
            stats.shoot_assigned += 1
    await db.flush()

    today = utc_today(now)
    stats.metric_rows = await _upsert_metrics(
        db,
        [
            (
                posts[video.video_id].id,
                today,
                {"views": video.views, "likes": video.likes, "comments": video.comments},
            )
            for video in videos
        ],
        platform=YOUTUBE,
        now=now,
    )


async def sync_linkedin_ads(
    db: AsyncSession,
    *,
    trigger: str,
    creative_urns: list[str] | None = None,
    log_run: bool = True,
    client: httpx.AsyncClient | None = None,
    now: datetime | None = None,
) -> SourceSyncStats:
    """Refresh LinkedIn ad posts and their daily metrics.

    ``creative_urns=None`` is the full daily sync: every ad campaign and
    creative in the ad account. Otherwise only those creatives' metrics are
    refreshed. Metrics cover the last ``LINKEDIN_ADS_LOOKBACK_DAYS`` days, or
    six months on the first full run. Failures are returned in ``error``.
    """
    now = now or datetime.now(timezone.utc)
    settings = get_settings()
    stats = SourceSyncStats(platform=LINKEDIN)
    config = await db.get(IntegrationSetting, LINKEDIN)
    integration = config.value_json if config else {}
    account_id = integration_or_env(
        integration, integration_key="adAccountId", env_value=settings.linkedin_ad_account_id
    )
    today = utc_today(now)

    own_client = client is None
    if own_client:
        client = _http_client()
    try:
        if not account_id:
            raise ConnectorError("LinkedIn ad account missing — set LINKEDIN_AD_ACCOUNT_ID")
        access_token, _ = await linkedin_ads_access_token(settings, integration)
        if not access_token:
            raise ConnectorError(
                "LinkedIn Ads credentials missing — set LINKEDIN_ADS_REFRESH_TOKEN with the app "
                "client id/secret"
            )
        api = dict(access_token=access_token, api_version=settings.linkedin_ads_api_version, client=client)
        if creative_urns is None:
            campaigns = await list_ad_campaigns(ad_account_id=account_id, **api)
            creatives = await list_creatives(ad_account_id=account_id, **api)
            await _store_creatives(db, creatives, campaigns, account_id=account_id, stats=stats)
            urns = [creative.urn for creative in creatives]
            backfill = not await _has_metrics(db, LINKEDIN)
        else:
            urns = list(creative_urns)
            backfill = False
        days_back = LINKEDIN_BACKFILL_DAYS if backfill else settings.linkedin_ads_lookback_days
        days = await fetch_creative_days(
            creative_urns=urns, start=today - timedelta(days=days_back), end=today, **api
        )
    except ConnectorError as exc:
        return await _failed(db, stats, exc, trigger=trigger, started=now, log_run=log_run)
    finally:
        if own_client:
            await client.aclose()

    post_ids = dict(
        (
            await db.execute(
                select(Post.provider_post_id, Post.id).where(
                    Post.platform == LINKEDIN, Post.provider_post_id.in_(urns)
                )
            )
        ).all()
    )
    if creative_urns is not None:
        stats.posts = len(post_ids)
    stats.metric_rows = await _upsert_metrics(
        db,
        [(post_ids[day.creative_urn], day.day, day.metrics) for day in days if day.creative_urn in post_ids],
        platform=LINKEDIN,
        now=now,
    )
    if log_run:
        _log_run(db, platform=LINKEDIN, trigger=trigger, started=now, error=None)
        await db.flush()
    return stats


async def _store_creatives(
    db: AsyncSession,
    creatives: list[Creative],
    campaigns: list[AdCampaign],
    *,
    account_id: str,
    stats: SourceSyncStats,
) -> None:
    campaign_by_id = {campaign.id: campaign for campaign in campaigns}
    linkedin_posts = list(
        (await db.execute(select(Post).where(Post.platform == LINKEDIN))).scalars()
    )
    ads = {post.provider_post_id: post for post in linkedin_posts if post.source == POST_SOURCE_LINKEDIN_ADS}
    # Organic posts by every URN LinkedIn may use for them.
    organic: dict[str, str] = {}
    for post in linkedin_posts:
        if post.source == POST_SOURCE_LINKEDIN_ADS:
            continue
        for urn in [post.provider_post_id, *(post.alt_ids or [])]:
            if urn:
                organic.setdefault(urn, post.id)

    for creative in creatives:
        campaign = campaign_by_id.get(creative.campaign_id)
        post = ads.get(creative.urn)
        if post is None:
            post = _new_post(
                platform=LINKEDIN,
                provider_post_id=creative.urn,
                source=POST_SOURCE_LINKEDIN_ADS,
                content_type="ad",
            )
            db.add(post)
            ads[creative.urn] = post
            stats.created += 1
        else:
            stats.updated += 1
        post.title = (creative.name or (campaign.name if campaign else "") or creative.urn)[:500]
        post.posted_at = creative.created_at
        post.provider_account_id = account_id
        post.alt_ids = [creative.reference] if creative.reference else None
        post.content_url = post_url(creative.reference) if creative.reference else None
        post.promotes_post_id = organic.get(creative.reference) if creative.reference else None
        if post.promotes_post_id:
            stats.promoted_found += 1
        post.platform_metadata = {
            **(post.platform_metadata or {}),
            "adCampaignId": creative.campaign_id,
            "adCampaignName": campaign.name if campaign else None,
            "adCampaignStatus": campaign.status if campaign else None,
            "creativeStatus": creative.status,
            "creativeType": creative.content_type,
            "reference": creative.reference,
        }
    stats.posts = len(creatives)
    await db.flush()


async def _has_metrics(db: AsyncSession, platform: str) -> bool:
    return (
        await db.execute(
            select(PostMetricDaily.id).where(PostMetricDaily.source == METRICS_SOURCE[platform]).limit(1)
        )
    ).first() is not None


def _new_post(**fields: Any) -> Post:
    return Post(id=str(uuid.uuid4()), share_count=0, impression_count=0, **fields)


async def _upsert_metrics(
    db: AsyncSession,
    rows: list[tuple[str, date, dict[str, Any]]],
    *,
    platform: str,
    now: datetime,
) -> int:
    """(post, day, metrics) rows; reruns update a day's row in place."""
    if not rows:
        return 0
    source, basis = METRICS_SOURCE[platform], METRICS_BASIS[platform]
    existing = {
        (row.post_id, row.metric_date): row
        for row in (
            await db.execute(
                select(PostMetricDaily).where(
                    PostMetricDaily.post_id.in_({post_id for post_id, _, _ in rows}),
                    PostMetricDaily.metric_date >= min(day for _, day, _ in rows),
                    PostMetricDaily.metric_date <= max(day for _, day, _ in rows),
                    PostMetricDaily.source == source,
                )
            )
        ).scalars()
    }
    for post_id, day, metrics in rows:
        row = existing.get((post_id, day))
        if row is None:
            row = PostMetricDaily(post_id=post_id, metric_date=day, source=source)
            db.add(row)
            existing[(post_id, day)] = row
        row.basis = basis
        row.metrics = metrics
        row.fetched_at = now
    await db.flush()
    return len(rows)


async def _failed(
    db: AsyncSession,
    stats: SourceSyncStats,
    exc: ConnectorError,
    *,
    trigger: str,
    started: datetime,
    log_run: bool,
) -> SourceSyncStats:
    stats.error = str(exc)
    if log_run:
        _log_run(db, platform=stats.platform, trigger=trigger, started=started, error=stats.error)
        await db.flush()
    return stats


def _log_run(
    db: AsyncSession,
    *,
    platform: str,
    trigger: str,
    started: datetime,
    error: str | None,
) -> None:
    db.add(
        PlatformSyncRun(
            campaign_id=None,
            platform=platform,
            trigger=trigger,
            started_at=started,
            finished_at=datetime.now(timezone.utc),
            status="error" if error else "success",
            error=error,
        )
    )


async def linked_provider_ids(
    db: AsyncSession, campaign_id: int, platform: str, *, source: str | None = None
) -> list[str]:
    """Provider IDs of the campaign's actively linked, non-excluded posts."""
    filters = [
        PostCampaignLink.campaign_id == campaign_id,
        PostCampaignLink.status == LINK_ACTIVE,
        Post.platform == platform,
        Post.excluded.is_(False),
        Post.provider_post_id.is_not(None),
    ]
    if source is not None:
        filters.append(Post.source == source)
    return list(
        (
            await db.execute(
                select(Post.provider_post_id)
                .join(PostCampaignLink, PostCampaignLink.post_id == Post.id)
                .where(*filters)
            )
        ).scalars()
    )


def _youtube_row(post: Post, metrics: dict[str, Any], _days: list[date]) -> dict[str, str]:
    return {
        "video id": post.provider_post_id or "",
        "title": post.title or "",
        "published": post.posted_at.isoformat() if post.posted_at else "",
        "url": post.content_url or "",
        "views": str(int(metrics.get("views") or 0)),
        "likes": str(int(metrics.get("likes") or 0)),
        "comments": str(int(metrics.get("comments") or 0)),
        "duration": format_duration(post.duration_seconds),
    }


_LINKEDIN_COUNTS = [
    ("impressions", "impressions"),
    ("clicks", "clicks"),
    ("landing page clicks", "landing_page_clicks"),
    ("engagements", "engagements"),
    ("reactions", "reactions"),
    ("comments", "comments"),
    ("shares", "shares"),
    ("follows", "follows"),
    ("video starts", "video_starts"),
    ("video views", "video_views"),
    ("video 25%", "video_25"),
    ("video 50%", "video_50"),
    ("video 75%", "video_75"),
    ("video completions", "video_completions"),
]


def _linkedin_row(post: Post, metrics: dict[str, Any], days: list[date]) -> dict[str, str]:
    meta = post.platform_metadata or {}
    row = {
        "creative": (post.provider_post_id or "").rsplit(":", 1)[-1],
        "name": post.title or "",
        "ad campaign": meta.get("adCampaignName") or meta.get("adCampaignId") or "",
        "promotes": post.content_url or "",
    }
    for key, name in _LINKEDIN_COUNTS:
        row[key] = metric_str(float(metrics.get(name) or 0))
    row["completion rate"] = safe_rate(
        float(metrics.get("video_completions") or 0), float(metrics.get("video_views") or 0)
    )
    row["ctr"] = safe_rate(float(metrics.get("clicks") or 0), float(metrics.get("impressions") or 0))
    row["cost"] = f"{float(metrics.get('cost') or 0):.2f}"
    row["first day"] = min(days).isoformat()
    row["last day"] = max(days).isoformat()
    return row


_ROW_BUILDERS = {YOUTUBE: _youtube_row, LINKEDIN: _linkedin_row}


def _sum(metrics_rows: list[dict[str, Any]]) -> dict[str, float]:
    total: dict[str, float] = defaultdict(float)
    for metrics in metrics_rows:
        for key, value in metrics.items():
            if isinstance(value, (int, float)):
                total[key] += value
    return dict(total)


async def campaign_post_snapshots(
    db: AsyncSession,
    campaign_id: int,
    *,
    window_start: date | None = None,
    window_end: date | None = None,
) -> dict[str, CampaignPlatformData]:
    """Per-platform snapshot rows from the campaign's linked posts.

    Only metrics rows dated inside the window count (CPR-44). YouTube rows
    are lifetime totals, so each video shows its latest row; LinkedIn Ads
    rows are per day, so each creative shows the sum of its days. The result
    is unsaved ``CampaignPlatformData`` objects, so existing readers work
    unchanged. A platform with linked posts but no metrics in the window is
    left out (missing).
    """
    snapshots: dict[str, CampaignPlatformData] = {}
    for platform, source in METRICS_SOURCE.items():
        filters = [
            PostCampaignLink.campaign_id == campaign_id,
            PostCampaignLink.status == LINK_ACTIVE,
            Post.platform == platform,
            Post.excluded.is_(False),
            PostMetricDaily.source == source,
        ]
        if window_start is not None:
            filters.append(PostMetricDaily.metric_date >= window_start)
        if window_end is not None:
            filters.append(PostMetricDaily.metric_date <= window_end)
        pairs = (
            await db.execute(
                select(Post, PostMetricDaily)
                .join(PostMetricDaily, PostMetricDaily.post_id == Post.id)
                .join(PostCampaignLink, PostCampaignLink.post_id == Post.id)
                .where(*filters)
                .order_by(Post.posted_at.desc().nulls_last(), Post.id, PostMetricDaily.metric_date)
            )
        ).all()
        if not pairs:
            continue
        by_post: dict[str, tuple[Post, list[PostMetricDaily]]] = {}
        for post, metric in pairs:
            by_post.setdefault(post.id, (post, []))[1].append(metric)
        rows = []
        for post, metrics in by_post.values():
            days = [metric.metric_date for metric in metrics]
            values = (
                metrics[-1].metrics
                if METRICS_BASIS[platform] == BASIS_LIFETIME
                else _sum([metric.metrics for metric in metrics])
            )
            rows.append(_ROW_BUILDERS[platform](post, values, days))
        snapshots[platform] = CampaignPlatformData(
            campaign_id=campaign_id,
            platform=platform,
            fetch_date=max(metric.metric_date for _, metric in pairs),
            status="available",
            synced_at=max(metric.fetched_at for _, metric in pairs),
            next_sync_at=None,
            row_count=len(rows),
            rows=rows,
            raw={"source": "posts", "metricsSource": source, "postCount": len(rows)},
            source="api",
            filename=None,
            error=None,
        )
    return snapshots
