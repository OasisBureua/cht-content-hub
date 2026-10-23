"""Social posts from platform APIs, with one metrics row per post per day (CPR-15).

YouTube: the daily sync lists every upload on the configured channels (plus
any YouTube post the Hub already has), upserts them into ``posts``, stores
today's lifetime views / likes / comments in ``post_metrics_daily`` and keeps
the legacy count columns on ``posts`` current for the public clips API. Shoot
playlists give new uploads their ``shoot_id``.

Campaign snapshots (``campaign_post_snapshots``) turn a campaign's linked
posts back into the per-platform rows that platform-data, the analytics
report and the report packet already read.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import OFFICIAL_YOUTUBE_CHANNEL_ID, Settings, get_settings
from models.campaign import CampaignPlatformData, PlatformSyncRun
from models.post import Post
from models.shoot import Shoot
from models.social import BASIS_LIFETIME, LINK_ACTIVE, PostCampaignLink, PostMetricDaily
from services.connectors.common import ConnectorError
from services.connectors.youtube import (
    YouTubeVideo,
    fetch_videos,
    format_duration,
    list_playlist_video_ids,
    uploads_playlist_id,
)

log = logging.getLogger(__name__)

YOUTUBE = "youtube"
POST_SOURCE_YOUTUBE = "youtube_api"
# post_metrics_daily.source per platform (where the numbers came from).
METRICS_SOURCE = {YOUTUBE: "youtube"}


@dataclass
class SourceSyncStats:
    platform: str
    videos: int = 0
    created: int = 0
    updated: int = 0
    not_returned: int = 0
    shoot_assigned: int = 0
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
    shoot playlist.
    Otherwise only the given videos are refreshed. A platform failure is
    returned in ``error``, not raised. With ``log_run`` the attempt is logged
    as a source-wide sync run (no campaign).
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
        stats.error = str(exc)
        if log_run:
            _log_run(db, trigger=trigger, started=now, error=stats.error)
            await db.flush()
        return stats
    finally:
        if own_client:
            await client.aclose()

    stats.videos = len(videos)
    stats.not_returned = len(set(ids)) - len(videos)
    await _store_youtube(db, videos, playlist_shoots, now=now, stats=stats)
    if log_run:
        _log_run(db, trigger=trigger, started=now, error=None)
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
    today = utc_today(now)
    for video in videos:
        post = posts.get(video.video_id)
        if post is None:
            post = Post(
                id=str(uuid.uuid4()),
                platform=YOUTUBE,
                provider_post_id=video.video_id,
                source=POST_SOURCE_YOUTUBE,
                channel="chm-official" if video.channel_id == OFFICIAL_YOUTUBE_CHANNEL_ID else None,
                content_type="video",
                share_count=0,
                impression_count=0,
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

    await _upsert_metrics(
        db,
        {
            posts[video.video_id].id: {
                "views": video.views,
                "likes": video.likes,
                "comments": video.comments,
            }
            for video in videos
        },
        source=METRICS_SOURCE[YOUTUBE],
        basis=BASIS_LIFETIME,
        day=today,
        now=now,
    )


async def _upsert_metrics(
    db: AsyncSession,
    metrics_by_post: dict[str, dict],
    *,
    source: str,
    basis: str,
    day: date,
    now: datetime,
) -> None:
    """Same-day reruns update the day's row in place."""
    if not metrics_by_post:
        return
    existing = {
        row.post_id: row
        for row in (
            await db.execute(
                select(PostMetricDaily).where(
                    PostMetricDaily.post_id.in_(list(metrics_by_post)),
                    PostMetricDaily.metric_date == day,
                    PostMetricDaily.source == source,
                )
            )
        ).scalars()
    }
    for post_id, metrics in metrics_by_post.items():
        row = existing.get(post_id)
        if row is None:
            db.add(
                PostMetricDaily(
                    post_id=post_id,
                    metric_date=day,
                    source=source,
                    basis=basis,
                    metrics=metrics,
                    fetched_at=now,
                )
            )
        else:
            row.basis = basis
            row.metrics = metrics
            row.fetched_at = now
    await db.flush()


def _log_run(
    db: AsyncSession,
    *,
    trigger: str,
    started: datetime,
    error: str | None,
) -> None:
    db.add(
        PlatformSyncRun(
            campaign_id=None,
            platform=YOUTUBE,
            trigger=trigger,
            started_at=started,
            finished_at=datetime.now(timezone.utc),
            status="error" if error else "success",
            error=error,
        )
    )


async def linked_provider_ids(db: AsyncSession, campaign_id: int, platform: str) -> list[str]:
    """Provider IDs of the campaign's actively linked, non-excluded posts."""
    return list(
        (
            await db.execute(
                select(Post.provider_post_id)
                .join(PostCampaignLink, PostCampaignLink.post_id == Post.id)
                .where(
                    PostCampaignLink.campaign_id == campaign_id,
                    PostCampaignLink.status == LINK_ACTIVE,
                    Post.platform == platform,
                    Post.excluded.is_(False),
                    Post.provider_post_id.is_not(None),
                )
            )
        ).scalars()
    )


def _youtube_row(post: Post, metrics: dict) -> dict[str, str]:
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


_ROW_BUILDERS = {YOUTUBE: _youtube_row}


async def campaign_post_snapshots(
    db: AsyncSession,
    campaign_id: int,
    *,
    window_start: date | None = None,
    window_end: date | None = None,
) -> dict[str, CampaignPlatformData]:
    """Per-platform snapshot rows from the campaign's linked posts.

    Each linked post contributes its latest metrics row inside the window
    (CPR-44 semantics: the snapshot day must fall in the window). The result
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
        ranked = (
            select(
                PostMetricDaily.id,
                func.row_number()
                .over(partition_by=PostMetricDaily.post_id, order_by=PostMetricDaily.metric_date.desc())
                .label("rank"),
            )
            .join(Post, Post.id == PostMetricDaily.post_id)
            .join(PostCampaignLink, PostCampaignLink.post_id == Post.id)
            .where(*filters)
            .subquery()
        )
        pairs = (
            await db.execute(
                select(Post, PostMetricDaily)
                .join(PostMetricDaily, PostMetricDaily.post_id == Post.id)
                .join(ranked, ranked.c.id == PostMetricDaily.id)
                .where(ranked.c.rank == 1)
                .order_by(Post.posted_at.desc().nulls_last(), Post.id)
            )
        ).all()
        if not pairs:
            continue
        rows = [_ROW_BUILDERS[platform](post, metric.metrics) for post, metric in pairs]
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
