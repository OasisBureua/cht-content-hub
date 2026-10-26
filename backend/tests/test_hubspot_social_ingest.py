"""CPR-56: HubSpot social parse (chunk 1) + posts/metrics upsert (chunk 2)."""

from __future__ import annotations

import copy
from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import api_headers
from models.campaign import Campaign
from models.post import Post
from models.social import (
    BASIS_LIFETIME,
    LINK_ACTIVE,
    LINK_HUBSPOT_CAMPAIGN,
    LINK_REMOVED,
    PostCampaignLink,
    PostMetricDaily,
)
from schemas.campaigns import CampaignUpdate
from services import campaigns as campaigns_service
from services import hubspot_social_ingest as hs
from services import post_links, social_posts

NOW = datetime(2026, 10, 26, 17, tzinfo=timezone.utc)

FIXTURE_RAW = {
    "hubspotCampaignId": "6169fb82-1c1d-448f-9a65-9a92bea0b1e9",
    "reportingPeriodStart": "2026-07-28",
    "reportingPeriodEnd": "2026-10-26",
    "socialPosts": [
        {
            "id": "387450805",
            "name": "LI caption",
            "network": "LinkedIn",
            "facebookClicks": 0,
            "linkedinClicks": 5,
            "twitterClicks": 0,
            "totalClicks": 5,
            "contentUrl": "https://www.youtube.com/watch?v=pxA4z47rNBw",
            "publishedAt": "2026-10-14T16:24:04.342Z",
            "channelKey": "LinkedInCompanyPage:99345473",
        },
        {
            "id": "387358222",
            "name": "FB caption",
            "network": "Facebook",
            "facebookClicks": 1,
            "linkedinClicks": 0,
            "twitterClicks": 0,
            "totalClicks": 1,
            "publishedAt": "2026-10-13T16:49:13.653Z",
            "channelKey": "FacebookPage:453669037825938",
        },
    ],
}


async def _campaign_with_social(
    db: AsyncSession,
    *,
    guid: str = "6169fb82-1c1d-448f-9a65-9a92bea0b1e9",
    raw: dict | None = None,
) -> Campaign:
    campaign = Campaign(
        name="CPR-56 HubSpot social",
        program_name="DB09",
        hubspot_campaign_id=guid,
        hubspot_raw_data=copy.deepcopy(FIXTURE_RAW if raw is None else raw),
    )
    db.add(campaign)
    await db.flush()
    return campaign


def test_link_constant_and_confidence() -> None:
    assert LINK_HUBSPOT_CAMPAIGN == "hubspot_campaign"
    assert post_links._CONFIDENCE[LINK_HUBSPOT_CAMPAIGN] == 1.0
    assert hs.POST_SOURCE_HUBSPOT == "hubspot"
    assert hs.METRICS_SOURCE_HUBSPOT == "hubspot"


def test_platform_from_network() -> None:
    assert hs.platform_from_network("LinkedIn", None) == "linkedin"
    assert hs.platform_from_network("Facebook", None) == "facebook"
    assert hs.platform_from_network("Instagram", None) == "instagram"
    assert hs.platform_from_network("X", None) == "x"
    assert hs.platform_from_network(None, "LinkedInCompanyPage:99") == "linkedin"
    assert hs.platform_from_network(None, "FacebookPage:1") == "facebook"
    assert hs.platform_from_network(None, None) == "hubspot"


def test_posts_from_normalized_social_posts() -> None:
    raw = {
        "hubspotCampaignId": "6169fb82-1c1d-448f-9a65-9a92bea0b1e9",
        "reportingPeriodStart": "2026-07-28",
        "reportingPeriodEnd": "2026-10-26",
        "socialPosts": [
            {
                "id": "387450805",
                "name": "LI caption",
                "network": "LinkedIn",
                "facebookClicks": 0,
                "linkedinClicks": 5,
                "twitterClicks": 0,
                "totalClicks": 5,
                "contentUrl": "https://www.youtube.com/watch?v=pxA4z47rNBw",
                "publishedAt": "2026-10-14T16:24:04.342Z",
                "channelKey": "LinkedInCompanyPage:99345473",
            },
            {
                "id": "387358222",
                "name": "FB caption",
                "network": "Facebook",
                "facebookClicks": 1,
                "linkedinClicks": 0,
                "twitterClicks": 0,
                "totalClicks": 1,
                "publishedAt": "2026-10-13T16:49:13.653Z",
                "channelKey": "FacebookPage:453669037825938",
            },
            # missing id — skipped
            {"name": "no id", "linkedinClicks": 9},
        ],
    }

    snap = hs.parse_hubspot_social_snapshot(raw)
    assert snap is not None
    assert snap.hubspot_campaign_id == "6169fb82-1c1d-448f-9a65-9a92bea0b1e9"
    assert snap.reporting_period_start == date(2026, 7, 28)
    assert snap.reporting_period_end == date(2026, 10, 26)
    assert len(snap.posts) == 2

    by_id = {p.provider_post_id: p for p in snap.posts}
    li = by_id["387450805"]
    assert li.platform == "linkedin"
    assert li.total_clicks == 5
    assert li.linkedin_clicks == 5
    assert li.content_url and "youtube.com" in li.content_url
    assert li.posted_at == datetime(2026, 10, 14, 16, 24, 4, 342000, tzinfo=timezone.utc)
    assert li.channel_key == "LinkedInCompanyPage:99345473"

    fb = by_id["387358222"]
    assert fb.platform == "facebook"
    assert fb.total_clicks == 1
    assert fb.facebook_clicks == 1


def test_posts_from_assets_by_type_when_social_posts_absent() -> None:
    raw = {
        "hubspotCampaignId": "abc",
        "assetsByType": {
            "SOCIAL_BROADCAST": {
                "results": [
                    {
                        "id": "soc-1",
                        "name": "LinkedIn share about DB09",
                        "metrics": {
                            "FACEBOOK_CLICKS": 0,
                            "LINKEDIN_CLICKS": 3,
                            "TWITTER_CLICKS": None,
                        },
                    },
                    {
                        "id": "soc-2",
                        "name": "Something",
                        "metrics": {"FACEBOOK_CLICKS": 2, "LINKEDIN_CLICKS": 0, "TWITTER_CLICKS": 0},
                    },
                    {"name": "no-id", "metrics": {"LINKEDIN_CLICKS": 99}},
                ]
            }
        },
    }

    posts = hs.posts_from_hubspot_raw(raw)
    assert len(posts) == 2
    assert posts[0].provider_post_id == "soc-1"
    assert posts[0].platform == "linkedin"
    assert posts[0].total_clicks == 3
    assert posts[1].provider_post_id == "soc-2"
    assert posts[1].platform == "facebook"
    assert posts[1].total_clicks == 2


def test_prefers_social_posts_over_assets_by_type() -> None:
    raw = {
        "socialPosts": [
            {
                "id": "from-normalized",
                "name": "A",
                "network": "LinkedIn",
                "facebookClicks": 0,
                "linkedinClicks": 1,
                "twitterClicks": 0,
                "totalClicks": 1,
            }
        ],
        "assetsByType": {
            "SOCIAL_BROADCAST": {
                "results": [
                    {
                        "id": "from-assets",
                        "name": "B",
                        "metrics": {"LINKEDIN_CLICKS": 9},
                    }
                ]
            }
        },
    }
    posts = hs.posts_from_hubspot_raw(raw)
    assert len(posts) == 1
    assert posts[0].provider_post_id == "from-normalized"


def test_empty_and_null_inputs() -> None:
    assert hs.parse_hubspot_social_snapshot(None) is None
    assert hs.parse_hubspot_social_snapshot("x") is None
    empty = hs.parse_hubspot_social_snapshot({})
    assert empty is not None
    assert empty.posts == ()
    assert empty.hubspot_campaign_id == ""
    assert hs.posts_from_hubspot_raw({"assetsByType": {"SOCIAL_BROADCAST": {"results": []}}}) == []
    assert hs.posts_from_hubspot_raw({"socialPosts": []}) == []


def test_null_click_values_become_zero() -> None:
    posts = hs.posts_from_hubspot_raw(
        {
            "socialPosts": [
                {
                    "id": "z",
                    "name": "Z",
                    "network": "LinkedIn",
                    "facebookClicks": None,
                    "linkedinClicks": None,
                    "twitterClicks": None,
                    "totalClicks": None,
                }
            ]
        }
    )
    assert len(posts) == 1
    assert posts[0].total_clicks == 0
    assert posts[0].linkedin_clicks == 0


def test_dedupes_duplicate_provider_ids() -> None:
    posts = hs.posts_from_hubspot_raw(
        {
            "socialPosts": [
                {
                    "id": "dup",
                    "name": "First",
                    "network": "LinkedIn",
                    "linkedinClicks": 1,
                    "facebookClicks": 0,
                    "twitterClicks": 0,
                    "totalClicks": 1,
                },
                {
                    "id": "dup",
                    "name": "Second",
                    "network": "LinkedIn",
                    "linkedinClicks": 9,
                    "facebookClicks": 0,
                    "twitterClicks": 0,
                    "totalClicks": 9,
                },
            ]
        }
    )
    assert len(posts) == 1
    assert posts[0].total_clicks == 1


# --- Chunk 2: upsert posts + post_metrics_daily ---


@pytest.mark.asyncio
async def test_ingest_upserts_posts_and_metrics(db_session: AsyncSession) -> None:
    campaign = await _campaign_with_social(db_session)

    stats = await hs.ingest_campaign_hubspot_social(db_session, campaign, now=NOW)

    assert stats.skipped is None
    assert (stats.posts, stats.created, stats.updated, stats.metric_rows) == (2, 2, 0, 2)
    assert stats.links_created == 2

    posts = list(
        (
            await db_session.execute(
                select(Post).where(Post.source == hs.POST_SOURCE_HUBSPOT).order_by(Post.provider_post_id)
            )
        ).scalars()
    )
    assert len(posts) == 2
    by_id = {p.provider_post_id: p for p in posts}
    li = by_id["387450805"]
    assert li.platform == "linkedin"
    assert li.title == "LI caption"
    assert li.platform_metadata["hubspotCampaignId"] == campaign.hubspot_campaign_id
    assert li.platform_metadata["totalClicks"] == 5

    metrics = list((await db_session.execute(select(PostMetricDaily))).scalars())
    assert len(metrics) == 2
    assert all(m.source == hs.METRICS_SOURCE_HUBSPOT for m in metrics)
    assert all(m.basis == BASIS_LIFETIME for m in metrics)
    assert all(m.metric_date == date(2026, 10, 26) for m in metrics)
    by_post = {m.post_id: m for m in metrics}
    assert by_post[li.id].metrics["clicks"] == 5
    assert by_post[li.id].metrics["linkedinClicks"] == 5
    assert by_post[by_id["387358222"].id].metrics["facebookClicks"] == 1

    links = list((await db_session.execute(select(PostCampaignLink))).scalars())
    assert len(links) == 2
    assert all(link.method == LINK_HUBSPOT_CAMPAIGN for link in links)
    assert all(link.status == LINK_ACTIVE for link in links)
    assert all(link.campaign_id == campaign.id for link in links)


@pytest.mark.asyncio
async def test_ingest_rerun_is_idempotent(db_session: AsyncSession) -> None:
    campaign = await _campaign_with_social(db_session)

    first = await hs.ingest_campaign_hubspot_social(db_session, campaign, now=NOW)
    assert first.created == 2

    # Bump clicks on fixture and re-ingest.
    raw = dict(campaign.hubspot_raw_data)
    posts = [dict(p) for p in raw["socialPosts"]]
    posts[0]["linkedinClicks"] = 9
    posts[0]["totalClicks"] = 9
    raw["socialPosts"] = posts
    campaign.hubspot_raw_data = raw
    await db_session.flush()

    second = await hs.ingest_campaign_hubspot_social(
        db_session, campaign, now=NOW.replace(hour=18)
    )
    assert (second.posts, second.created, second.updated, second.metric_rows) == (2, 0, 2, 2)

    post_count = (
        await db_session.execute(
            select(func.count()).select_from(Post).where(Post.source == hs.POST_SOURCE_HUBSPOT)
        )
    ).scalar_one()
    metric_count = (
        await db_session.execute(select(func.count()).select_from(PostMetricDaily))
    ).scalar_one()
    assert post_count == 2
    assert metric_count == 2

    li = (
        await db_session.execute(
            select(Post).where(Post.provider_post_id == "387450805", Post.platform == "linkedin")
        )
    ).scalar_one()
    metric = (
        await db_session.execute(
            select(PostMetricDaily).where(
                PostMetricDaily.post_id == li.id,
                PostMetricDaily.source == hs.METRICS_SOURCE_HUBSPOT,
            )
        )
    ).scalar_one()
    assert metric.metrics["clicks"] == 9
    assert li.platform_metadata["totalClicks"] == 9


@pytest.mark.asyncio
async def test_ingest_soft_noop_without_guid(db_session: AsyncSession) -> None:
    campaign = await _campaign_with_social(db_session, guid="")
    stats = await hs.ingest_campaign_hubspot_social(db_session, campaign, now=NOW)
    assert stats.skipped == "no_hubspot_campaign_id"
    assert stats.posts == 0
    assert (await db_session.execute(select(func.count()).select_from(Post))).scalar_one() == 0


@pytest.mark.asyncio
async def test_ingest_soft_noop_without_social(db_session: AsyncSession) -> None:
    campaign = await _campaign_with_social(
        db_session,
        raw={"hubspotCampaignId": "6169fb82-1c1d-448f-9a65-9a92bea0b1e9"},
    )
    stats = await hs.ingest_campaign_hubspot_social(db_session, campaign, now=NOW)
    assert stats.skipped == "no_social_payload"
    assert stats.created == 0
    assert (await db_session.execute(select(func.count()).select_from(Post))).scalar_one() == 0


@pytest.mark.asyncio
async def test_ingest_uses_utc_today_when_period_end_missing(db_session: AsyncSession) -> None:
    raw = {
        "hubspotCampaignId": "6169fb82-1c1d-448f-9a65-9a92bea0b1e9",
        "socialPosts": [
            {
                "id": "only-1",
                "name": "X",
                "network": "X",
                "facebookClicks": 0,
                "linkedinClicks": 0,
                "twitterClicks": 2,
                "totalClicks": 2,
            }
        ],
    }
    campaign = await _campaign_with_social(db_session, raw=raw)
    stats = await hs.ingest_campaign_hubspot_social(db_session, campaign, now=NOW)
    assert stats.metric_rows == 1
    metric = (await db_session.execute(select(PostMetricDaily))).scalar_one()
    assert metric.metric_date == date(2026, 10, 26)


# --- Chunk 3: hubspot_campaign links + EXTRA_RULES ---


@pytest.mark.asyncio
async def test_person_removed_link_stays_removed_on_reingest(db_session: AsyncSession) -> None:
    campaign = await _campaign_with_social(db_session)
    await hs.ingest_campaign_hubspot_social(db_session, campaign, now=NOW)

    link = (
        await db_session.execute(
            select(PostCampaignLink).where(PostCampaignLink.campaign_id == campaign.id).limit(1)
        )
    ).scalar_one()
    link.status = LINK_REMOVED
    link.removed_by = "admin@chm"
    link.removed_at = NOW
    await db_session.flush()

    stats = await hs.ingest_campaign_hubspot_social(db_session, campaign, now=NOW)
    assert stats.links_created == 0
    assert stats.links_skipped_person == 1
    assert stats.links_reactivated == 0

    refreshed = (
        await db_session.execute(
            select(PostCampaignLink).where(PostCampaignLink.id == link.id)
        )
    ).scalar_one()
    assert refreshed.status == LINK_REMOVED
    assert refreshed.removed_by == "admin@chm"


@pytest.mark.asyncio
async def test_extra_rule_wrong_guid_produces_no_link(db_session: AsyncSession) -> None:
    campaign = Campaign(
        name="Has GUID",
        program_name="DB09",
        hubspot_campaign_id="6169fb82-1c1d-448f-9a65-9a92bea0b1e9",
    )
    orphan = Post(
        id="orphan-hs",
        platform="linkedin",
        provider_post_id="wrong-guid-post",
        source=hs.POST_SOURCE_HUBSPOT,
        platform_metadata={"hubspotCampaignId": "00000000-0000-0000-0000-000000000000"},
        share_count=0,
        impression_count=0,
    )
    db_session.add_all([campaign, orphan])
    await db_session.flush()

    hs.register_hubspot_link_rule()
    proposals = await hs.hubspot_campaign_extra_rule(
        db_session,
        post_links.LinkContext(posts=[orphan], campaigns=[campaign]),
    )
    assert proposals == []

    await post_links.relink(db_session, now=NOW)
    count = (
        await db_session.execute(select(func.count()).select_from(PostCampaignLink))
    ).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_extra_rule_matches_guid_and_relink_creates_link(db_session: AsyncSession) -> None:
    campaign = Campaign(
        name="Match GUID",
        program_name="DB09",
        hubspot_campaign_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    )
    post = Post(
        id="match-hs",
        platform="facebook",
        provider_post_id="fb-1",
        source=hs.POST_SOURCE_HUBSPOT,
        platform_metadata={"hubspotCampaignId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"},
        share_count=0,
        impression_count=0,
    )
    db_session.add_all([campaign, post])
    await db_session.flush()

    stats = await post_links.relink(db_session, now=NOW)
    assert stats.by_method.get(LINK_HUBSPOT_CAMPAIGN) == 1
    link = (await db_session.execute(select(PostCampaignLink))).scalar_one()
    assert (link.post_id, link.campaign_id, link.method, link.status) == (
        post.id,
        campaign.id,
        LINK_HUBSPOT_CAMPAIGN,
        LINK_ACTIVE,
    )


@pytest.mark.asyncio
async def test_linker_removed_link_is_reactivated_on_ingest(db_session: AsyncSession) -> None:
    campaign = await _campaign_with_social(db_session)
    await hs.ingest_campaign_hubspot_social(db_session, campaign, now=NOW)
    link = (await db_session.execute(select(PostCampaignLink))).scalars().first()
    assert link is not None
    link.status = LINK_REMOVED
    link.removed_by = post_links.LINKER
    link.removed_at = NOW
    await db_session.flush()

    stats = await hs.ingest_campaign_hubspot_social(db_session, campaign, now=NOW)
    assert stats.links_reactivated >= 1
    refreshed = (
        await db_session.execute(select(PostCampaignLink).where(PostCampaignLink.id == link.id))
    ).scalar_one()
    assert refreshed.status == LINK_ACTIVE
    assert refreshed.removed_by is None


# --- Chunk 4: PATCH hubspot_raw_data triggers soft-fail ingest ---


@pytest.mark.asyncio
async def test_patch_hubspot_raw_data_ingests_posts_links_metrics(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    create = await client.post(
        "/api/admin/campaigns",
        headers=api_headers(),
        json={
            "name": "CPR-56 PATCH",
            "hubspot_campaign_id": "6169fb82-1c1d-448f-9a65-9a92bea0b1e9",
        },
    )
    assert create.status_code == 201
    campaign_id = create.json()["id"]

    patch = await client.patch(
        f"/api/admin/campaigns/{campaign_id}",
        headers=api_headers(),
        json={"hubspot_raw_data": FIXTURE_RAW},
    )
    assert patch.status_code == 200
    body = patch.json()
    assert body.get("hubspotCampaignId") or body.get("hubspot_campaign_id")

    posts = (
        await db_session.execute(select(func.count()).select_from(Post).where(Post.source == hs.POST_SOURCE_HUBSPOT))
    ).scalar_one()
    metrics = (await db_session.execute(select(func.count()).select_from(PostMetricDaily))).scalar_one()
    links = (
        await db_session.execute(
            select(func.count()).select_from(PostCampaignLink).where(
                PostCampaignLink.campaign_id == campaign_id,
                PostCampaignLink.method == LINK_HUBSPOT_CAMPAIGN,
                PostCampaignLink.status == LINK_ACTIVE,
            )
        )
    ).scalar_one()
    assert (posts, metrics, links) == (2, 2, 2)


@pytest.mark.asyncio
async def test_patch_without_hubspot_raw_data_does_not_ingest(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    create = await client.post(
        "/api/admin/campaigns",
        headers=api_headers(),
        json={
            "name": "No raw touch",
            "hubspot_campaign_id": "6169fb82-1c1d-448f-9a65-9a92bea0b1e9",
            "hubspot_raw_data": FIXTURE_RAW,
        },
    )
    campaign_id = create.json()["id"]

    patch = await client.patch(
        f"/api/admin/campaigns/{campaign_id}",
        headers=api_headers(),
        json={"status": "data_needed"},
    )
    assert patch.status_code == 200
    assert (
        await db_session.execute(select(func.count()).select_from(Post))
    ).scalar_one() == 0


@pytest.mark.asyncio
async def test_patch_hubspot_raw_without_social_succeeds(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    create = await client.post(
        "/api/admin/campaigns",
        headers=api_headers(),
        json={"name": "Empty social", "hubspot_campaign_id": "guid-1"},
    )
    campaign_id = create.json()["id"]

    patch = await client.patch(
        f"/api/admin/campaigns/{campaign_id}",
        headers=api_headers(),
        json={"hubspot_raw_data": {"hubspotCampaignId": "guid-1"}},
    )
    assert patch.status_code == 200
    assert (
        await db_session.execute(select(func.count()).select_from(Post))
    ).scalar_one() == 0


@pytest.mark.asyncio
async def test_patch_soft_fails_when_ingest_raises(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign = Campaign(
        name="Soft fail",
        program_name="DB09",
        hubspot_campaign_id="6169fb82-1c1d-448f-9a65-9a92bea0b1e9",
    )
    db_session.add(campaign)
    await db_session.flush()

    async def boom(*_args, **_kwargs):
        raise RuntimeError("ingest exploded")

    monkeypatch.setattr(hs, "ingest_campaign_hubspot_social", boom)

    out = await campaigns_service.update_campaign(
        db_session,
        campaign.id,
        CampaignUpdate(hubspot_raw_data=FIXTURE_RAW),
    )
    assert out.id == campaign.id
    assert out.hubspot_raw_data is not None


@pytest.mark.asyncio
async def test_patch_name_only_still_works_when_raw_already_present(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Regression: updating unrelated fields must not require / break on social."""
    create = await client.post(
        "/api/admin/campaigns",
        headers=api_headers(),
        json={
            "name": "Before",
            "hubspot_campaign_id": "6169fb82-1c1d-448f-9a65-9a92bea0b1e9",
            "hubspot_raw_data": FIXTURE_RAW,
        },
    )
    campaign_id = create.json()["id"]
    patch = await client.patch(
        f"/api/admin/campaigns/{campaign_id}",
        headers=api_headers(),
        json={"name": "After"},
    )
    assert patch.status_code == 200
    assert patch.json()["name"] == "After"
    assert (
        await db_session.execute(select(func.count()).select_from(Post))
    ).scalar_one() == 0


# --- Chunk 5: backfill all campaigns with stored HubSpot snapshots ---


@pytest.mark.asyncio
async def test_backfill_ingests_campaigns_with_stored_social(
    db_session: AsyncSession,
) -> None:
    good = await _campaign_with_social(db_session)
    empty = Campaign(
        name="No social rows",
        hubspot_campaign_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        hubspot_raw_data={"hubspotCampaignId": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"},
    )
    no_guid = Campaign(name="No GUID", hubspot_campaign_id="", hubspot_raw_data=FIXTURE_RAW)
    db_session.add_all([empty, no_guid])
    await db_session.flush()

    stats = await hs.ingest_all_campaigns_with_hubspot(db_session, now=NOW)

    assert stats.campaigns == 2  # good + empty (no_guid excluded by query)
    assert stats.ingested == 1
    assert stats.skipped == 1
    assert stats.posts_created == 2
    assert stats.metric_rows == 2
    assert stats.links_created == 2
    assert stats.errors == []

    posts = (
        await db_session.execute(
            select(func.count()).select_from(Post).where(Post.source == hs.POST_SOURCE_HUBSPOT)
        )
    ).scalar_one()
    assert posts == 2
    links = (
        await db_session.execute(
            select(func.count()).select_from(PostCampaignLink).where(
                PostCampaignLink.campaign_id == good.id,
                PostCampaignLink.method == LINK_HUBSPOT_CAMPAIGN,
            )
        )
    ).scalar_one()
    assert links == 2


@pytest.mark.asyncio
async def test_backfill_soft_fails_one_campaign_and_continues(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = await _campaign_with_social(db_session, guid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    second = await _campaign_with_social(
        db_session,
        guid="cccccccc-cccc-cccc-cccc-cccccccccccc",
        raw={
            **FIXTURE_RAW,
            "hubspotCampaignId": "cccccccc-cccc-cccc-cccc-cccccccccccc",
            "socialPosts": [
                {
                    "id": "other-1",
                    "name": "Other",
                    "network": "LinkedIn",
                    "linkedinClicks": 2,
                    "facebookClicks": 0,
                    "twitterClicks": 0,
                    "totalClicks": 2,
                }
            ],
        },
    )
    await db_session.flush()

    real = hs.ingest_campaign_hubspot_social

    async def flaky(db, campaign, *, now=None):
        if campaign.id == first.id:
            raise RuntimeError("boom on first")
        return await real(db, campaign, now=now)

    monkeypatch.setattr(hs, "ingest_campaign_hubspot_social", flaky)

    stats = await hs.ingest_all_campaigns_with_hubspot(db_session, now=NOW)
    assert len(stats.errors) == 1
    assert str(first.id) in stats.errors[0]
    assert stats.ingested == 1
    assert stats.posts_created == 1

    other = (
        await db_session.execute(
            select(Post).where(Post.provider_post_id == "other-1")
        )
    ).scalar_one()
    assert other is not None
    assert second.id  # second campaign survived


@pytest.mark.asyncio
async def test_backfill_idempotent_on_rerun(db_session: AsyncSession) -> None:
    await _campaign_with_social(db_session)
    first = await hs.ingest_all_campaigns_with_hubspot(db_session, now=NOW)
    second = await hs.ingest_all_campaigns_with_hubspot(db_session, now=NOW)
    assert first.posts_created == 2
    assert second.posts_created == 0
    assert second.posts_updated == 2
    assert (
        await db_session.execute(
            select(func.count()).select_from(Post).where(Post.source == hs.POST_SOURCE_HUBSPOT)
        )
    ).scalar_one() == 2


# --- Reviewer fixes: identity drift + campaign GUID stamp ---


@pytest.mark.asyncio
async def test_platform_drift_updates_in_place_no_duplicate_post(
    db_session: AsyncSession,
) -> None:
    """Enrich can change network mapping; must not create a second post/link."""
    campaign = await _campaign_with_social(
        db_session,
        raw={
            "hubspotCampaignId": "6169fb82-1c1d-448f-9a65-9a92bea0b1e9",
            "reportingPeriodEnd": "2026-10-26",
            "socialPosts": [
                {
                    "id": "drift-1",
                    "name": "No network yet",
                    # no network → platform hubspot
                    "facebookClicks": 0,
                    "linkedinClicks": 3,
                    "twitterClicks": 0,
                    "totalClicks": 3,
                }
            ],
        },
    )
    first = await hs.ingest_campaign_hubspot_social(db_session, campaign, now=NOW)
    assert first.created == 1
    post = (
        await db_session.execute(select(Post).where(Post.provider_post_id == "drift-1"))
    ).scalar_one()
    assert post.platform == "hubspot"
    post_id = post.id

    # Second sync: same broadcast id, now with LinkedIn network (enrich).
    campaign.hubspot_raw_data = {
        "hubspotCampaignId": "6169fb82-1c1d-448f-9a65-9a92bea0b1e9",
        "reportingPeriodEnd": "2026-10-26",
        "socialPosts": [
            {
                "id": "drift-1",
                "name": "LI caption",
                "network": "LinkedIn",
                "facebookClicks": 0,
                "linkedinClicks": 3,
                "twitterClicks": 0,
                "totalClicks": 3,
                "channelKey": "LinkedInCompanyPage:1",
            }
        ],
    }
    await db_session.flush()
    second = await hs.ingest_campaign_hubspot_social(db_session, campaign, now=NOW)
    assert second.created == 0
    assert second.updated == 1

    posts = list(
        (
            await db_session.execute(select(Post).where(Post.provider_post_id == "drift-1"))
        ).scalars()
    )
    assert len(posts) == 1
    assert posts[0].id == post_id
    assert posts[0].platform == "linkedin"

    links = list(
        (
            await db_session.execute(
                select(PostCampaignLink).where(
                    PostCampaignLink.campaign_id == campaign.id,
                    PostCampaignLink.status == LINK_ACTIVE,
                )
            )
        ).scalars()
    )
    assert len(links) == 1
    assert links[0].post_id == post_id


@pytest.mark.asyncio
async def test_prior_duplicate_orphan_loses_guid_so_relink_drops_it(
    db_session: AsyncSession,
) -> None:
    """If a prior bug left hubspot+linkedin rows for one id, demote the orphan."""
    guid = "6169fb82-1c1d-448f-9a65-9a92bea0b1e9"
    campaign = await _campaign_with_social(
        db_session,
        guid=guid,
        raw={
            "hubspotCampaignId": guid,
            "socialPosts": [
                {
                    "id": "dup-id",
                    "name": "LI",
                    "network": "LinkedIn",
                    "linkedinClicks": 1,
                    "facebookClicks": 0,
                    "twitterClicks": 0,
                    "totalClicks": 1,
                }
            ],
        },
    )
    canon = Post(
        id="canon-dup",
        platform="linkedin",
        provider_post_id="dup-id",
        source=hs.POST_SOURCE_HUBSPOT,
        platform_metadata={"hubspotCampaignId": guid},
        share_count=0,
        impression_count=0,
    )
    orphan = Post(
        id="orphan-dup",
        platform="hubspot",
        provider_post_id="dup-id",
        source=hs.POST_SOURCE_HUBSPOT,
        platform_metadata={"hubspotCampaignId": guid},
        share_count=0,
        impression_count=0,
    )
    db_session.add_all([canon, orphan])
    db_session.add(
        PostCampaignLink(
            post_id=orphan.id,
            campaign_id=campaign.id,
            method=LINK_HUBSPOT_CAMPAIGN,
            status=LINK_ACTIVE,
            created_by=post_links.LINKER,
        )
    )
    await db_session.flush()

    await hs.ingest_campaign_hubspot_social(db_session, campaign, now=NOW)

    refreshed = await db_session.get(Post, "orphan-dup")
    assert refreshed is not None
    assert not (refreshed.platform_metadata or {}).get("hubspotCampaignId")

    refreshed_canon = await db_session.get(Post, "canon-dup")
    assert refreshed_canon is not None
    assert refreshed_canon.platform_metadata["hubspotCampaignId"] == guid

    await post_links.relink(db_session, now=NOW)
    active = list(
        (
            await db_session.execute(
                select(PostCampaignLink).where(
                    PostCampaignLink.status == LINK_ACTIVE,
                    PostCampaignLink.method == LINK_HUBSPOT_CAMPAIGN,
                )
            )
        ).scalars()
    )
    assert len(active) == 1
    assert active[0].post_id == canon.id


@pytest.mark.asyncio
async def test_metadata_guid_always_campaign_row_not_snapshot(
    db_session: AsyncSession,
) -> None:
    campaign_guid = "11111111-1111-1111-1111-111111111111"
    wrong_snapshot_guid = "22222222-2222-2222-2222-222222222222"
    other = Campaign(
        name="Other owner of snapshot GUID",
        hubspot_campaign_id=wrong_snapshot_guid,
    )
    campaign = Campaign(
        name="Actual ingest target",
        hubspot_campaign_id=campaign_guid,
        hubspot_raw_data={
            "hubspotCampaignId": wrong_snapshot_guid,
            "socialPosts": [
                {
                    "id": "guid-post",
                    "name": "A",
                    "network": "LinkedIn",
                    "linkedinClicks": 1,
                    "facebookClicks": 0,
                    "twitterClicks": 0,
                    "totalClicks": 1,
                }
            ],
        },
    )
    db_session.add_all([other, campaign])
    await db_session.flush()

    stats = await hs.ingest_campaign_hubspot_social(db_session, campaign, now=NOW)
    assert stats.links_created == 1

    post = (
        await db_session.execute(select(Post).where(Post.provider_post_id == "guid-post"))
    ).scalar_one()
    assert post.platform_metadata["hubspotCampaignId"] == campaign_guid

    link = (await db_session.execute(select(PostCampaignLink))).scalar_one()
    assert link.campaign_id == campaign.id

    # Nightly EXTRA_RULE must not steal the link to the other campaign.
    await post_links.relink(db_session, now=NOW)
    links = list((await db_session.execute(select(PostCampaignLink))).scalars())
    active = [lnk for lnk in links if lnk.status == LINK_ACTIVE]
    assert len(active) == 1
    assert active[0].campaign_id == campaign.id


@pytest.mark.asyncio
async def test_daily_job_runs_hubspot_backfill_after_sources(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from jobs.platform_metrics_sync_core import sync_platform_metrics

    await _campaign_with_social(db_session)
    order: list[str] = []
    real_backfill = hs.ingest_all_campaigns_with_hubspot

    async def yt(_db, *, trigger, now=None):
        order.append("youtube")
        return social_posts.SourceSyncStats(platform="youtube")

    async def li(_db, *, trigger, now=None):
        order.append("linkedin")
        return social_posts.SourceSyncStats(platform="linkedin")

    async def tracking_backfill(db, *, now=None):
        order.append("hubspot")
        return await real_backfill(db, now=now)

    async def _tok(*_a, **_k):
        return "token", None

    monkeypatch.setattr("services.social_posts.sync_youtube", yt)
    monkeypatch.setattr("services.social_posts.sync_linkedin_ads", li)
    monkeypatch.setattr(
        "services.hubspot_social_ingest.ingest_all_campaigns_with_hubspot", tracking_backfill
    )
    monkeypatch.setattr("jobs.platform_metrics_sync_core.linkedin_ads_access_token", _tok)

    stats = await sync_platform_metrics(db_session, now=NOW)
    assert order == ["youtube", "linkedin", "hubspot"]
    assert stats.hubspot is not None
    assert stats.hubspot.ingested == 1
    assert stats.hubspot.posts_created == 2
    assert (
        await db_session.execute(
            select(func.count()).select_from(Post).where(Post.source == hs.POST_SOURCE_HUBSPOT)
        )
    ).scalar_one() == 2
