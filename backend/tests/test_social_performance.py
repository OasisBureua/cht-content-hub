"""CPR-61: social performance block on the report packet and report inputs."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import api_headers
from models.post import Post
from models.social import BASIS_DAILY, BASIS_LIFETIME, PostCampaignLink, PostMetricDaily
from services.social_performance import build_social_performance

FETCHED = datetime(2026, 10, 27, 14, tzinfo=timezone.utc)


async def _campaign(client: AsyncClient, name: str = "Social campaign") -> int:
    response = await client.post(
        "/api/admin/campaigns",
        headers=api_headers(),
        json={"name": name, "platforms": ["youtube", "linkedin"]},
    )
    return response.json()["id"]


def _post(db: AsyncSession, post_id: str, platform: str, source: str, *, title: str = "", excluded=False) -> Post:
    post = Post(
        id=post_id,
        platform=platform,
        provider_post_id=f"pp-{post_id}",
        source=source,
        title=title or post_id,
        content_url=f"https://example.com/{post_id}",
        excluded=excluded,
    )
    db.add(post)
    return post


def _link(db: AsyncSession, post_id: str, campaign_id: int, status: str = "active") -> None:
    db.add(PostCampaignLink(post_id=post_id, campaign_id=campaign_id, method="shoot", status=status))


def _metric(db: AsyncSession, post_id: str, day: date, source: str, metrics: dict, basis=BASIS_LIFETIME) -> None:
    db.add(
        PostMetricDaily(
            post_id=post_id, metric_date=day, source=source, basis=basis, metrics=metrics, fetched_at=FETCHED
        )
    )


async def _seed(db: AsyncSession, campaign_id: int) -> None:
    # YouTube: snapshots before and inside the window; the latest in-window one counts.
    _post(db, "yt1", "youtube", "youtube_api", title="Big video")
    _link(db, "yt1", campaign_id)
    _metric(db, "yt1", date(2026, 9, 30), "youtube", {"views": 900, "likes": 9, "comments": 1})
    _metric(db, "yt1", date(2026, 10, 10), "youtube", {"views": 1000, "likes": 10, "comments": 2})
    _metric(db, "yt1", date(2026, 10, 20), "youtube", {"views": 1500, "likes": 15, "comments": 3})
    _metric(db, "yt1", date(2026, 11, 5), "youtube", {"views": 9999, "likes": 99, "comments": 9})
    # Second video with no snapshot before the window: no "gained" for it.
    _post(db, "yt2", "youtube", "youtube_api", title="Small video")
    _link(db, "yt2", campaign_id)
    _metric(db, "yt2", date(2026, 10, 15), "youtube", {"views": 100, "likes": 1, "comments": 0})
    # LinkedIn ad: daily rows summed inside the window; cost never surfaces.
    _post(db, "ad1", "linkedin", "linkedin_ads", title="Boost")
    _link(db, "ad1", campaign_id)
    for day, imp, clicks in ((date(2026, 9, 30), 999, 99), (date(2026, 10, 5), 400, 4), (date(2026, 10, 6), 600, 6)):
        _metric(
            db, "ad1", day, "linkedin_ads",
            {"impressions": imp, "clicks": clicks, "engagements": 10, "video_views": 50, "cost": 25.5},
            basis=BASIS_DAILY,
        )
    # HubSpot also reports clicks for the ad: LinkedIn Ads stays the source.
    _metric(db, "ad1", date(2026, 10, 20), "hubspot", {"clicks": 500})
    # Organic LinkedIn post published through HubSpot: clicks from HubSpot.
    _post(db, "hs1", "linkedin", "hubspot", title="Organic post")
    _link(db, "hs1", campaign_id)
    _metric(db, "hs1", date(2026, 10, 20), "hubspot", {"clicks": 7, "linkedinClicks": 7})
    # Facebook post through HubSpot.
    _post(db, "fb1", "facebook", "hubspot", title="FB post")
    _link(db, "fb1", campaign_id)
    _metric(db, "fb1", date(2026, 10, 20), "hubspot", {"clicks": 3})
    # Ignored: excluded post, removed link, linked post without metrics.
    _post(db, "gone", "youtube", "youtube_api", excluded=True)
    _link(db, "gone", campaign_id)
    _metric(db, "gone", date(2026, 10, 20), "youtube", {"views": 5000})
    _post(db, "unlinked", "youtube", "youtube_api")
    _link(db, "unlinked", campaign_id, status="removed")
    _metric(db, "unlinked", date(2026, 10, 20), "youtube", {"views": 7000})
    _post(db, "nometrics", "youtube", "youtube_api")
    _link(db, "nometrics", campaign_id)
    await db.flush()


WINDOW = dict(window_start=date(2026, 10, 1), window_end=date(2026, 10, 31))


@pytest.mark.asyncio
async def test_channels_totals_sources_and_top_posts(client: AsyncClient, db_session: AsyncSession):
    campaign_id = await _campaign(client)
    await _seed(db_session, campaign_id)

    result = await build_social_performance(db_session, campaign_id, requested=None, **WINDOW)
    perf = result.performance

    assert (perf.linked_posts, perf.posts_with_metrics) == (6, 5)
    assert [c.channel for c in perf.channels] == ["youtube", "linkedin", "facebook"]
    youtube, linkedin, facebook = perf.channels

    # Latest in-window snapshot (Oct 20), not the Nov 5 one; gained only for yt1.
    assert youtube.organic == {"views": 1600.0, "likes": 16.0, "comments": 3.0, "viewsGained": 600.0}
    assert youtube.as_of == date(2026, 10, 20)
    assert [p.post_id for p in youtube.top_posts] == ["yt1", "yt2"]
    assert youtube.top_posts[0].metrics["viewsGained"] == 600.0
    assert "viewsGained" not in youtube.top_posts[1].metrics
    assert youtube.metric_sources["organic.views"] == "youtube"

    # Ad days inside the window only; HubSpot clicks for the ad are not added.
    assert linkedin.paid == {
        "impressions": 1000.0, "clicks": 10.0, "engagements": 20.0, "videoViews": 100.0, "ctr": 0.01,
    }
    assert linkedin.organic == {"clicks": 7.0}
    assert (linkedin.posts, linkedin.paid_posts) == (2, 1)
    assert linkedin.metric_sources == {
        "organic.clicks": "hubspot",
        "paid.clicks": "linkedin_ads",
        "paid.engagements": "linkedin_ads",
        "paid.impressions": "linkedin_ads",
        "paid.videoViews": "linkedin_ads",
    }
    assert all("cost" not in p.metrics for p in linkedin.top_posts)
    assert linkedin.top_posts[0].paid is True

    assert facebook.organic == {"clicks": 3.0}
    assert perf.notes and "lifetime totals" in perf.notes[0]
    assert (result.completeness.status, result.completeness.row_count) == ("ok", 5)


@pytest.mark.asyncio
async def test_toggles_limit_channels_and_sources(client: AsyncClient, db_session: AsyncSession):
    campaign_id = await _campaign(client)
    await _seed(db_session, campaign_id)

    only_youtube = await build_social_performance(db_session, campaign_id, requested={"youtube"}, **WINDOW)
    assert [c.channel for c in only_youtube.performance.channels] == ["youtube"]

    # LinkedIn on, HubSpot off: the ad counts, the HubSpot-only organic post does not.
    no_hubspot = await build_social_performance(db_session, campaign_id, requested={"linkedin"}, **WINDOW)
    linkedin = no_hubspot.performance.channels[0]
    assert (linkedin.channel, linkedin.posts, linkedin.organic) == ("linkedin", 1, {})

    none = await build_social_performance(db_session, campaign_id, requested={"sessions"}, **WINDOW)
    assert (none.performance, none.completeness) == (None, None)


@pytest.mark.asyncio
async def test_last_good_row_and_empty_window(client: AsyncClient, db_session: AsyncSession):
    campaign_id = await _campaign(client)
    await _seed(db_session, campaign_id)

    # Window ends before the latest sync: the last row inside it is used.
    early = await build_social_performance(
        db_session, campaign_id, requested={"youtube"},
        window_start=date(2026, 10, 1), window_end=date(2026, 10, 12),
    )
    assert early.performance.channels[0].organic["views"] == 1000.0

    # Nothing in the window: no block, completeness missing.
    empty = await build_social_performance(
        db_session, campaign_id, requested=None,
        window_start=date(2026, 12, 1), window_end=date(2026, 12, 31),
    )
    assert empty.performance is None
    assert (empty.completeness.status, empty.completeness.row_count) == ("missing", 0)


@pytest.mark.asyncio
async def test_packet_and_report_inputs_carry_social(client: AsyncClient, db_session: AsyncSession):
    campaign_id = await _campaign(client)
    await _seed(db_session, campaign_id)
    params = {"windowStart": "2026-10-01", "windowEnd": "2026-10-31"}

    packet = (
        await client.get(f"/api/campaigns/{campaign_id}/report-packet", headers=api_headers(), params=params)
    ).json()
    social = packet["socialPerformance"]
    assert [c["channel"] for c in social["channels"]] == ["youtube", "linkedin", "facebook"]
    assert social["channels"][0]["topPosts"][0]["postId"] == "yt1"
    assert social["channels"][1]["metricSources"]["paid.impressions"] == "linkedin_ads"
    assert packet["inputCompleteness"]["socialPosts"]["rowCount"] == 5

    inputs = (
        await client.get(
            f"/api/admin/campaigns/{campaign_id}/report-inputs", headers=api_headers(), params=params
        )
    ).json()
    assert inputs["inputCompleteness"]["socialPosts"]["status"] == "ok"

    off = (
        await client.get(
            f"/api/campaigns/{campaign_id}/report-packet",
            headers=api_headers(),
            params={**params, "sources": ["sessions"]},
        )
    ).json()
    assert off["socialPerformance"] is None
    assert "socialPosts" not in off["inputCompleteness"]
