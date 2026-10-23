"""CPR-15: YouTube posts + daily metrics, automatic links, and campaign reads."""

from __future__ import annotations

from datetime import date, datetime, timezone

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import api_headers
from models.campaign import Campaign, PlatformSyncRun
from models.post import Post
from models.shoot import Shoot
from models.social import PostCampaignLink, PostMetricDaily
from models.wordpress_projection import WordPressPost
from services import post_links, social_posts

NOW = datetime(2026, 10, 23, 14, tzinfo=timezone.utc)
CHANNELS = {"UUaaa": ["v1", "v2"], "UUbbb": ["v3"]}
SHOOT_PLAYLIST = "PLshoot1"


def _video(video_id: str, channel: str, views: int, title: str = "") -> dict:
    return {
        "id": video_id,
        "snippet": {
            "title": title or f"Video {video_id}",
            "description": "",
            "publishedAt": "2026-10-20T15:00:00Z",
            "channelId": channel,
            "channelTitle": f"Channel {channel}",
        },
        "statistics": {"viewCount": str(views), "likeCount": "2", "commentCount": "1"},
        "contentDetails": {"duration": "PT5M"},
    }


class FakeYouTube:
    """Uploads playlists, one shoot playlist, and videos.list."""

    def __init__(self, views: int = 100, titles: dict[str, str] | None = None):
        self.views = views
        self.titles = titles or {}
        self.video_requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if request.url.path.endswith("/playlistItems"):
            playlist = params["playlistId"]
            ids = CHANNELS.get(playlist) or (["v3", "old1"] if playlist == SHOOT_PLAYLIST else None)
            if ids is None:
                return httpx.Response(404, json={"error": {"message": "playlistNotFound"}})
            return httpx.Response(
                200, json={"items": [{"contentDetails": {"videoId": vid}} for vid in ids]}
            )
        assert request.url.path.endswith("/videos")
        self.video_requests.append(params["id"])
        channel_of = {"v1": "UCaaa", "v2": "UCaaa", "v3": "UCbbb", "old1": "UCaaa"}
        items = [
            _video(vid, channel_of[vid], self.views, self.titles.get(vid, ""))
            for vid in params["id"].split(",")
            if vid in channel_of
        ]
        return httpx.Response(200, json={"items": items})


@pytest.fixture
def youtube(monkeypatch) -> FakeYouTube:
    fake = FakeYouTube()
    monkeypatch.setenv("YOUTUBE_API_KEY", "yt-key")
    monkeypatch.setenv("YOUTUBE_CHANNEL_IDS", "UCaaa,UCbbb")
    from config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(
        social_posts,
        "_http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: fake(r))),
    )
    yield fake
    get_settings.cache_clear()


async def _campaign(client: AsyncClient, name: str, platforms: list[str] | None = None) -> int:
    response = await client.post(
        "/api/admin/campaigns",
        headers=api_headers(),
        json={"name": name, "platforms": platforms or ["youtube"]},
    )
    return response.json()["id"]


async def _post(db: AsyncSession, video_id: str) -> Post:
    return (
        await db.execute(select(Post).where(Post.platform == "youtube", Post.provider_post_id == video_id))
    ).scalar_one()


async def _links(db: AsyncSession) -> dict[tuple[str, int], tuple[str, str]]:
    rows = (await db.execute(select(PostCampaignLink))).scalars()
    return {(link.post_id, link.campaign_id): (link.method, link.status) for link in rows}


@pytest.mark.asyncio
async def test_full_youtube_sync_stores_posts_snapshot_and_shoot(db_session: AsyncSession, youtube):
    db_session.add(Post(id="legacy", platform="youtube", provider_post_id="old1", source="webhook",
                        channel="branded-az", view_count=5))
    db_session.add(Shoot(id="shoot-1", name="Shoot", youtube_playlist_id=SHOOT_PLAYLIST))
    await db_session.flush()

    stats = await social_posts.sync_youtube(db_session, trigger="schedule", now=NOW)

    assert (stats.error, stats.videos, stats.created, stats.updated) == (None, 4, 3, 1)
    v1, v3, legacy = [await _post(db_session, vid) for vid in ("v1", "v3", "old1")]
    assert (v1.source, v1.provider_account_id, v1.view_count, v1.duration_seconds) == (
        "youtube_api", "UCaaa", 100, 300
    )
    assert v1.content_url == "https://www.youtube.com/watch?v=v1"
    # Existing posts keep their source and client label; counts are refreshed.
    assert (legacy.source, legacy.channel, legacy.view_count) == ("webhook", "branded-az", 100)
    assert (v3.shoot_id, legacy.shoot_id) == ("shoot-1", "shoot-1")

    metrics = (await db_session.execute(select(PostMetricDaily))).scalars().all()
    assert len(metrics) == 4
    assert {m.metric_date for m in metrics} == {date(2026, 10, 23)}
    assert metrics[0].metrics == {"views": 100, "likes": 2, "comments": 1}

    youtube.views = 150
    await social_posts.sync_youtube(db_session, trigger="schedule", now=NOW)
    assert (await db_session.execute(select(func.count()).select_from(PostMetricDaily))).scalar_one() == 4
    runs = (await db_session.execute(select(PlatformSyncRun))).scalars().all()
    assert [(r.campaign_id, r.platform, r.status) for r in runs] == [(None, "youtube", "success")] * 2


@pytest.mark.asyncio
async def test_youtube_sync_failure_is_logged_not_raised(db_session: AsyncSession, monkeypatch, youtube):
    monkeypatch.setattr(
        social_posts,
        "_http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(403, text="quota"))),
    )
    stats = await social_posts.sync_youtube(db_session, trigger="schedule", now=NOW)
    assert stats.error.startswith("YouTube playlistItems.list failed 403")
    run = (await db_session.execute(select(PlatformSyncRun))).scalar_one()
    assert (run.campaign_id, run.status) == (None, "error")


@pytest.mark.asyncio
async def test_linker_rules(client: AsyncClient, db_session: AsyncSession, youtube):
    tagged = await _campaign(client, "Veppanu Spotlight")
    by_shoot = await _campaign(client, "Shoot campaign")
    by_map = await _campaign(client, "Mapped campaign")
    campaign = await db_session.get(Campaign, tagged)
    campaign.tags = ["RIG-26-02_VEP_SPL2"]
    db_session.add(Shoot(id="shoot-1", name="Shoot", youtube_playlist_id=SHOOT_PLAYLIST, campaign_id=by_shoot))
    db_session.add(
        WordPressPost(
            post_id=1, post_type="post", slug="veppanu-rig-26-02_vep_spl2", title="Veppanu",
            status="publish", permalink="https://chm.example/veppanu", modified_gmt=NOW,
            youtube_video_id="v2", last_event_id=1,
        )
    )
    await client.patch(
        "/api/admin/integrations",
        headers=api_headers(),
        json={"platforms": {"youtube": {"enabled": True, "campaignMap": {str(by_map): {"youtubeVideoIds": ["v1"]}}}}},
    )
    youtube.titles = {"v1": "Dr. Hamilton on VEP | RIG-26-02_VEP_SPL2"}
    await social_posts.sync_youtube(db_session, trigger="schedule", now=NOW)
    ad = Post(id="ad-1", platform="linkedin", provider_post_id="urn:li:sponsoredCreative:9",
              source="linkedin_ads", promotes_post_id=(await _post(db_session, "v3")).id)
    db_session.add(ad)
    await db_session.flush()

    stats = await post_links.relink(db_session, now=NOW)

    v1, v2, v3, old1 = [(await _post(db_session, vid)).id for vid in ("v1", "v2", "v3", "old1")]
    assert await _links(db_session) == {
        (v1, by_map): ("campaign_map", "active"),
        (v1, tagged): ("content_id", "active"),
        (v2, tagged): ("wordpress_embed", "active"),
        (v3, by_shoot): ("shoot", "active"),
        (old1, by_shoot): ("shoot", "active"),
        ("ad-1", by_shoot): ("promoted_post", "active"),
    }
    assert (stats.created, stats.active) == (6, 6)
    link = (
        await db_session.execute(select(PostCampaignLink).where(PostCampaignLink.post_id == v1,
                                                                PostCampaignLink.campaign_id == tagged))
    ).scalar_one()
    assert (link.chm_content_id, link.created_by) == ("RIG-26-02_VEP_SPL2", "linker")


@pytest.mark.asyncio
async def test_linker_never_overrides_people(client: AsyncClient, db_session: AsyncSession, youtube):
    first = await _campaign(client, "First")
    second = await _campaign(client, "Second")
    shoot = Shoot(id="shoot-1", name="Shoot", youtube_playlist_id=SHOOT_PLAYLIST, campaign_id=first)
    db_session.add(shoot)
    await social_posts.sync_youtube(db_session, trigger="schedule", now=NOW)
    await post_links.relink(db_session, now=NOW)
    v3 = (await _post(db_session, "v3")).id
    old1 = (await _post(db_session, "old1")).id

    # A person removes one automatic link and adds a manual one elsewhere.
    removed = (
        await db_session.execute(select(PostCampaignLink).where(PostCampaignLink.post_id == old1))
    ).scalar_one()
    removed.status, removed.removed_by = "removed", "admin@chm"
    db_session.add(PostCampaignLink(post_id=v3, campaign_id=second, method="manual", created_by="admin@chm"))
    await db_session.flush()

    # The shoot moves to the second campaign.
    shoot.campaign_id = second
    await db_session.flush()
    stats = await post_links.relink(db_session, now=NOW)

    links = await _links(db_session)
    assert links[(old1, first)] == ("shoot", "removed")  # stays removed by the person
    assert links[(v3, first)] == ("shoot", "removed")  # no rule supports it any more
    assert links[(v3, second)] == ("manual", "active")  # manual link untouched
    assert links[(old1, second)] == ("shoot", "active")
    assert stats.removed == 1


@pytest.mark.asyncio
async def test_campaign_reads_youtube_from_linked_posts(client: AsyncClient, db_session: AsyncSession, youtube):
    campaign_id = await _campaign(client, "Linked")
    db_session.add(Shoot(id="shoot-1", name="Shoot", youtube_playlist_id=SHOOT_PLAYLIST, campaign_id=campaign_id))
    await social_posts.sync_youtube(db_session, trigger="schedule", now=NOW)
    await post_links.relink(db_session, now=NOW)

    data = await client.get(f"/api/admin/campaigns/{campaign_id}/platform-data", headers=api_headers())
    item = next(i for i in data.json()["items"] if i["platform"] == "youtube")
    assert (item["status"], item["rowCount"], item["fetchDate"]) == ("available", 2, "2026-10-23")

    packet = await client.get(
        f"/api/campaigns/{campaign_id}/report-packet",
        headers=api_headers(),
        params={"sources": ["youtube"], "windowStart": "2026-10-01", "windowEnd": "2026-10-31"},
    )
    body = packet.json()
    youtube_slice = next(s for s in body["platformSlices"] if s["platform"] == "youtube")
    assert sorted(row["video id"] for row in youtube_slice["rows"]) == ["old1", "v3"]
    assert youtube_slice["rows"][0]["views"] == "100"
    assert body["inputCompleteness"]["youtube"]["status"] == "ok"

    outside = await client.get(
        f"/api/campaigns/{campaign_id}/report-packet",
        headers=api_headers(),
        params={"sources": ["youtube"], "windowStart": "2026-09-01", "windowEnd": "2026-09-30"},
    )
    assert outside.json()["inputCompleteness"]["youtube"]["status"] == "missing"


@pytest.mark.asyncio
async def test_sync_now_refreshes_only_linked_videos(client: AsyncClient, db_session: AsyncSession, youtube):
    campaign_id = await _campaign(client, "Sync now")
    unlinked = await _campaign(client, "Nothing linked")
    db_session.add(Shoot(id="shoot-1", name="Shoot", youtube_playlist_id=SHOOT_PLAYLIST, campaign_id=campaign_id))
    await social_posts.sync_youtube(db_session, trigger="schedule", now=NOW)
    youtube.video_requests.clear()

    sync = await client.post(
        f"/api/admin/campaigns/{campaign_id}/platforms/youtube/sync", headers=api_headers()
    )
    assert sync.status_code == 200
    assert sync.json()["rowCount"] == 2
    assert sorted(youtube.video_requests[0].split(",")) == ["old1", "v3"]

    none = await client.post(
        f"/api/admin/campaigns/{unlinked}/platforms/youtube/sync", headers=api_headers()
    )
    assert none.status_code == 400
    assert "No YouTube posts linked" in none.json()["message"]


def test_content_ids_match_the_v1_1_format_only():
    assert post_links.content_ids(
        "RIG-26-02_VEP_SPL2 and DSI-26-01_DB09_RND3, not DS-26-01_DB09 or RIG-26-02_VEP_SPL2X"
    ) == ["RIG-26-02_VEP_SPL2", "DSI-26-01_DB09_RND3"]


@pytest.mark.asyncio
async def test_admin_maps_a_shoot_to_a_campaign_and_relinks(
    client: AsyncClient, db_session: AsyncSession, youtube
):
    campaign_id = await _campaign(client, "Shoot mapped by admin")
    db_session.add(Shoot(id="shoot-1", name="Shoot", youtube_playlist_id=SHOOT_PLAYLIST))
    await social_posts.sync_youtube(db_session, trigger="schedule", now=NOW)

    listed = await client.get("/api/admin/shoots", headers=api_headers())
    assert listed.json()["items"] == [
        {
            "id": "shoot-1",
            "name": "Shoot",
            "shootDate": None,
            "youtubePlaylistId": SHOOT_PLAYLIST,
            "campaignId": None,
            "postCount": 2,
        }
    ]

    mapped = await client.patch(
        "/api/admin/shoots/shoot-1/campaign", headers=api_headers(), json={"campaignId": campaign_id}
    )
    assert mapped.status_code == 200
    assert (mapped.json()["shoot"]["campaignId"], mapped.json()["linksCreated"]) == (campaign_id, 2)

    cleared = await client.patch(
        "/api/admin/shoots/shoot-1/campaign", headers=api_headers(), json={"campaignId": None}
    )
    assert (cleared.json()["shoot"]["campaignId"], cleared.json()["linksRemoved"]) == (None, 2)

    missing = await client.patch(
        "/api/admin/shoots/shoot-1/campaign", headers=api_headers(), json={"campaignId": 999}
    )
    assert missing.status_code == 404
    assert (
        await client.patch("/api/admin/shoots/nope/campaign", headers=api_headers(), json={"campaignId": None})
    ).status_code == 404
