"""Social performance of a campaign's linked posts, for the report packet (CPR-61).

Each post contributes each metric from one source only, the first in
``SOURCE_PRIORITY`` that has it, so channel totals never add the same post's
number twice. Lifetime sources (YouTube, HubSpot) use the post's latest row
inside the window; when the latest sync failed, that is the last good row.
Daily sources (LinkedIn Ads) sum the window's days. Ad spend is not
included: it stays internal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.post import Post
from models.social import BASIS_DAILY, LINK_ACTIVE, PostCampaignLink, PostMetricDaily
from schemas.report_packet import (
    SocialChannelOut,
    SocialPerformanceOut,
    SocialPostSummaryOut,
    SourceCompletenessOut,
    SourceStatus,
)
from schemas.report_sources import wants_source

# metrics row field -> report metric name, per post_metrics_daily.source.
# Sources from CPR-59 (LinkedIn organic) and CPR-60 (HubSpot Social export)
# slot in here and in SOURCE_PRIORITY.
SOURCE_METRICS: dict[str, dict[str, str]] = {
    "youtube": {"views": "views", "likes": "likes", "comments": "comments"},
    "linkedin_ads": {
        "impressions": "impressions",
        "clicks": "clicks",
        "engagements": "engagements",
        "video_views": "videoViews",
        "video_completions": "videoCompletions",
    },
    "hubspot": {"clicks": "clicks"},
}
SOURCE_PRIORITY = ("youtube", "linkedin_ads", "hubspot")

# Report source toggle that must be on for a source's numbers to count.
SOURCE_TOGGLE = {"youtube": "youtube", "linkedin_ads": "linkedin", "hubspot": "hubspot"}
# posts.platform -> channel, and the toggle that shows the channel.
CHANNEL_TOGGLE = {
    "youtube": "youtube",
    "linkedin": "linkedin",
    "facebook": "meta",
    "instagram": "meta",
    "x": "hubspot",
}
SOCIAL_TOGGLES = ("youtube", "linkedin", "meta", "hubspot")
CHANNEL_ORDER = ("youtube", "linkedin", "facebook", "instagram", "x", "other")

PAID_POST_SOURCES = frozenset({"linkedin_ads"})
# Ranking for top posts: the first metric a post has.
RANK_METRICS = ("views", "impressions", "clicks", "engagements")
TOP_POSTS = 5


@dataclass
class _PostValues:
    post: Post
    metrics: dict[str, float] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    as_of: date | None = None
    fetched_at: datetime | None = None
    views_gained: float | None = None


@dataclass
class SocialPerformanceResult:
    performance: SocialPerformanceOut | None
    completeness: SourceCompletenessOut | None


def _channel(platform: str) -> str:
    return platform if platform in CHANNEL_TOGGLE else "other"


def _channel_wanted(requested: set[str] | None, channel: str) -> bool:
    return wants_source(requested, CHANNEL_TOGGLE.get(channel, "hubspot"))


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _post_values(
    post: Post,
    rows: list[PostMetricDaily],
    *,
    sources: tuple[str, ...],
    window_start: date | None,
    window_end: date | None,
) -> _PostValues:
    values = _PostValues(post=post)
    in_window = [
        r
        for r in rows
        if (window_start is None or r.metric_date >= window_start)
        and (window_end is None or r.metric_date <= window_end)
    ]
    for source in sources:
        source_rows = [r for r in in_window if r.source == source]
        if not source_rows:
            continue
        daily = source_rows[0].basis == BASIS_DAILY
        if daily:
            totals: dict[str, float] = {}
            for row in source_rows:
                for field_name, value in (row.metrics or {}).items():
                    number = _number(value)
                    if number is not None:
                        totals[field_name] = totals.get(field_name, 0.0) + number
        else:
            latest = max(source_rows, key=lambda r: r.metric_date)
            totals = {
                k: n for k, v in (latest.metrics or {}).items() if (n := _number(v)) is not None
            }
        used = False
        for field_name, metric in SOURCE_METRICS[source].items():
            if metric in values.metrics or field_name not in totals:
                continue
            values.metrics[metric] = totals[field_name]
            values.sources[metric] = source
            used = True
        if not used:
            continue
        last = max(source_rows, key=lambda r: r.metric_date)
        if values.as_of is None or last.metric_date > values.as_of:
            values.as_of = last.metric_date
        fetched = max(r.fetched_at for r in source_rows)
        if values.fetched_at is None or fetched > values.fetched_at:
            values.fetched_at = fetched
        if source == "youtube" and window_start is not None and "views" in values.metrics:
            before = [r for r in rows if r.source == source and r.metric_date < window_start]
            if before:
                base = _number((max(before, key=lambda r: r.metric_date).metrics or {}).get("views"))
                if base is not None:
                    values.views_gained = max(0.0, values.metrics["views"] - base)
    return values


def _summary(values: _PostValues) -> SocialPostSummaryOut:
    post = values.post
    metrics = dict(values.metrics)
    if values.views_gained is not None:
        metrics["viewsGained"] = values.views_gained
    return SocialPostSummaryOut(
        post_id=post.id,
        title=post.title,
        url=post.content_url,
        posted_at=post.posted_at,
        paid=post.source in PAID_POST_SOURCES,
        metrics=metrics,
    )


def _rank(values: _PostValues) -> float:
    for metric in RANK_METRICS:
        if metric in values.metrics:
            return values.metrics[metric]
    return 0.0


def _channel_out(channel: str, posts: list[_PostValues]) -> SocialChannelOut:
    organic: dict[str, float] = {}
    paid: dict[str, float] = {}
    metric_sources: dict[str, set[str]] = {}
    gained = [v.views_gained for v in posts if v.views_gained is not None]
    for values in posts:
        is_paid = values.post.source in PAID_POST_SOURCES
        bucket, prefix = (paid, "paid") if is_paid else (organic, "organic")
        for metric, number in values.metrics.items():
            bucket[metric] = bucket.get(metric, 0.0) + number
            metric_sources.setdefault(f"{prefix}.{metric}", set()).add(values.sources[metric])
    if gained:
        organic["viewsGained"] = sum(gained)
    if paid.get("impressions"):
        paid["ctr"] = round(paid.get("clicks", 0.0) / paid["impressions"], 4)
    top = sorted(posts, key=lambda v: (-_rank(v), v.post.id))[:TOP_POSTS]
    return SocialChannelOut(
        channel=channel,
        posts=len(posts),
        paid_posts=sum(1 for v in posts if v.post.source in PAID_POST_SOURCES),
        organic=organic,
        paid=paid,
        metric_sources={k: ", ".join(sorted(v)) for k, v in sorted(metric_sources.items())},
        as_of=max((v.as_of for v in posts if v.as_of), default=None),
        top_posts=[_summary(v) for v in top],
    )


async def build_social_performance(
    db: AsyncSession,
    campaign_id: int,
    *,
    requested: set[str] | None,
    window_start: date | None = None,
    window_end: date | None = None,
) -> SocialPerformanceResult:
    """Social block and its ``socialPosts`` completeness entry.

    Both are None when no social toggle is requested.
    """
    if not any(wants_source(requested, toggle) for toggle in SOCIAL_TOGGLES):
        return SocialPerformanceResult(None, None)
    sources = tuple(s for s in SOURCE_PRIORITY if wants_source(requested, SOURCE_TOGGLE[s]))

    posts = [
        post
        for post in (
            await db.execute(
                select(Post)
                .join(PostCampaignLink, PostCampaignLink.post_id == Post.id)
                .where(
                    PostCampaignLink.campaign_id == campaign_id,
                    PostCampaignLink.status == LINK_ACTIVE,
                    Post.excluded.is_(False),
                )
            )
        ).scalars()
        if _channel_wanted(requested, _channel(post.platform))
    ]
    rows_by_post: dict[str, list[PostMetricDaily]] = {}
    if posts and sources:
        query = select(PostMetricDaily).where(
            PostMetricDaily.post_id.in_([p.id for p in posts]),
            PostMetricDaily.source.in_(sources),
        )
        if window_end is not None:
            query = query.where(PostMetricDaily.metric_date <= window_end)
        for row in (await db.execute(query)).scalars():
            rows_by_post.setdefault(row.post_id, []).append(row)

    by_channel: dict[str, list[_PostValues]] = {}
    fetched_at: datetime | None = None
    for post in posts:
        values = _post_values(
            post,
            rows_by_post.get(post.id, []),
            sources=sources,
            window_start=window_start,
            window_end=window_end,
        )
        if not values.metrics:
            continue
        by_channel.setdefault(_channel(post.platform), []).append(values)
        if values.fetched_at and (fetched_at is None or values.fetched_at > fetched_at):
            fetched_at = values.fetched_at

    with_metrics = sum(len(v) for v in by_channel.values())
    completeness = SourceCompletenessOut(
        fetched_at=fetched_at,
        row_count=with_metrics,
        status=SourceStatus.OK if with_metrics else SourceStatus.MISSING,
    )
    if not with_metrics:
        return SocialPerformanceResult(None, completeness)

    notes: list[str] = []
    youtube = by_channel.get("youtube", [])
    if youtube and any(v.views_gained is None for v in youtube):
        notes.append(
            "YouTube views are lifetime totals as of the date shown; views gained in the "
            "window need a snapshot from before the window starts."
        )
    return SocialPerformanceResult(
        SocialPerformanceOut(
            linked_posts=len(posts),
            posts_with_metrics=with_metrics,
            channels=[
                _channel_out(channel, by_channel[channel])
                for channel in CHANNEL_ORDER
                if channel in by_channel
            ],
            notes=notes,
        ),
        completeness,
    )
