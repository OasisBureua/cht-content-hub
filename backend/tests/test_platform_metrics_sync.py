"""CPR-15: platform sync outcomes, report-input statuses, and the daily job."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import api_headers
from models.campaign import PlatformSyncRun
from models.post import Post
from models.social import PostCampaignLink
from services import social_posts
from services.connectors import ConnectorError


async def _campaign(client: AsyncClient, name: str, platforms: list[str]) -> int:
    response = await client.post(
        "/api/admin/campaigns",
        headers=api_headers(),
        json={"name": name, "platforms": platforms},
    )
    return response.json()["id"]


async def _runs(db: AsyncSession, campaign_id: int | None) -> list[str]:
    where = (
        PlatformSyncRun.campaign_id.is_(None)
        if campaign_id is None
        else PlatformSyncRun.campaign_id == campaign_id
    )
    return list((await db.execute(select(PlatformSyncRun.status).where(where))).scalars())


def _settings(monkeypatch, **env: str) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    from config import get_settings

    get_settings.cache_clear()


async def _token(*_args, **_kwargs):
    return "token", None


async def _linked_ad(db: AsyncSession, campaign_id: int) -> None:
    db.add(Post(id="ad-1", platform="linkedin", provider_post_id="urn:li:sponsoredCreative:1",
                source="linkedin_ads"))
    db.add(PostCampaignLink(post_id="ad-1", campaign_id=campaign_id, method="manual", created_by="admin"))
    await db.flush()


@pytest.mark.asyncio
async def test_campaign_with_nothing_linked_is_unmapped_not_an_error(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    _settings(monkeypatch, YOUTUBE_API_KEY="yt-key")
    campaign_id = await _campaign(client, "Nothing linked", ["youtube", "linkedin"])

    for platform, label in (("youtube", "No YouTube posts linked"), ("linkedin", "No LinkedIn ads linked")):
        sync = await client.post(
            f"/api/admin/campaigns/{campaign_id}/platforms/{platform}/sync", headers=api_headers()
        )
        assert sync.status_code == 400
        assert label in sync.json()["message"]
    assert await _runs(db_session, campaign_id) == ["unmapped", "unmapped"]

    packet = await client.get(
        f"/api/campaigns/{campaign_id}/report-packet",
        headers=api_headers(),
        params={"sources": ["youtube", "linkedin"]},
    )
    completeness = packet.json()["inputCompleteness"]
    assert completeness["youtube"]["status"] == completeness["linkedin"]["status"] == "missing"


@pytest.mark.asyncio
async def test_failed_daily_sync_shows_as_error_in_report_inputs(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    async def expired(*_args, **_kwargs):
        raise ConnectorError("LinkedIn Ads refresh token expired or revoked")

    _settings(monkeypatch, LINKEDIN_AD_ACCOUNT_ID="515103342")
    monkeypatch.setattr("services.social_posts.linkedin_ads_access_token", expired)
    campaign_id = await _campaign(client, "LinkedIn campaign", ["linkedin"])

    stats = await social_posts.sync_linkedin_ads(db_session, trigger="schedule")
    assert stats.error == "LinkedIn Ads refresh token expired or revoked"
    assert await _runs(db_session, None) == ["error"]

    packet = await client.get(
        f"/api/campaigns/{campaign_id}/report-packet",
        headers=api_headers(),
        params={"sources": ["linkedin"]},
    )
    linkedin = packet.json()["inputCompleteness"]["linkedin"]
    assert linkedin["status"] == "error"
    assert linkedin["fetchedAt"] is not None


@pytest.mark.asyncio
async def test_failed_sync_run_is_committed_before_the_error_response(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    # get_db rolls back when the HTTPException escapes, so the failed run must
    # already be committed by then.
    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="LinkedIn is down")

    _settings(monkeypatch, LINKEDIN_AD_ACCOUNT_ID="515103342")
    monkeypatch.setattr("services.social_posts.linkedin_ads_access_token", _token)
    monkeypatch.setattr(
        social_posts, "_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(broken))
    )
    campaign_id = await _campaign(client, "Committed failure", ["linkedin"])
    await _linked_ad(db_session, campaign_id)

    committed: list[list[str]] = []
    real_commit = db_session.commit

    async def tracking_commit():
        committed.append(await _runs(db_session, campaign_id))
        await real_commit()

    monkeypatch.setattr(db_session, "commit", tracking_commit)
    sync = await client.post(
        f"/api/admin/campaigns/{campaign_id}/platforms/linkedin/sync", headers=api_headers()
    )
    assert sync.status_code == 502
    assert "LinkedIn adAnalytics error 500" in sync.json()["message"]
    assert committed == [["error"]]


@pytest.mark.asyncio
async def test_csv_platform_without_a_connector_is_not_enabled(
    client: AsyncClient, db_session: AsyncSession
):
    campaign_id = await _campaign(client, "Meta campaign", ["meta"])
    await client.patch(
        "/api/admin/integrations",
        headers=api_headers(),
        json={"platforms": {"meta": {"enabled": False}}},
    )

    sync = await client.post(
        f"/api/admin/campaigns/{campaign_id}/platforms/meta/sync", headers=api_headers()
    )
    assert sync.status_code == 400
    assert await _runs(db_session, campaign_id) == ["not_enabled"]


@pytest.mark.asyncio
async def test_daily_job_syncs_each_source_then_relinks(db_session: AsyncSession, monkeypatch):
    from jobs.platform_metrics_sync_core import sync_platform_metrics

    calls: list[str] = []

    def fake(platform):
        async def run(_db, *, trigger, now=None):
            calls.append(f"{platform}:{trigger}")
            return social_posts.SourceSyncStats(platform=platform, posts=3)

        return run

    monkeypatch.setattr("services.social_posts.sync_youtube", fake("youtube"))
    monkeypatch.setattr("services.social_posts.sync_linkedin_ads", fake("linkedin"))
    monkeypatch.setattr("jobs.platform_metrics_sync_core.linkedin_ads_access_token", _token)

    stats = await sync_platform_metrics(db_session)

    assert calls == ["youtube:schedule", "linkedin:schedule"]
    assert (stats.youtube.posts, stats.linkedin.posts, stats.errors) == (3, 3, [])
    assert stats.links is not None


@pytest.mark.asyncio
async def test_daily_job_dry_run_calls_nothing(db_session: AsyncSession, monkeypatch):
    from jobs.platform_metrics_sync_core import sync_platform_metrics

    async def fail(*_args, **_kwargs):
        raise AssertionError("dry run must not call anything")

    for target in (
        "services.social_posts.sync_youtube",
        "services.social_posts.sync_linkedin_ads",
        "services.post_links.relink",
        "jobs.platform_metrics_sync_core.linkedin_ads_access_token",
    ):
        monkeypatch.setattr(target, fail)

    stats = await sync_platform_metrics(db_session, dry_run=True)
    assert (stats.youtube, stats.linkedin, stats.links) == (None, None, None)


@pytest.mark.asyncio
async def test_daily_job_logs_network_failures_and_moves_on(
    db_session: AsyncSession, monkeypatch
):
    from jobs.platform_metrics_sync_core import sync_platform_metrics

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    _settings(monkeypatch, YOUTUBE_API_KEY="yt-key", LINKEDIN_AD_ACCOUNT_ID="515103342")
    monkeypatch.setattr("services.social_posts.linkedin_ads_access_token", _token)
    monkeypatch.setattr("jobs.platform_metrics_sync_core.linkedin_ads_access_token", _token)
    monkeypatch.setattr(
        social_posts, "_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(offline))
    )

    stats = await sync_platform_metrics(db_session)

    assert stats.errors == [
        "youtube: YouTube playlistItems.list request failed (ConnectError)",
        "linkedin: LinkedIn adCampaigns request failed (ConnectError)",
    ]
    assert stats.links is not None
    runs = (await db_session.execute(select(PlatformSyncRun))).scalars().all()
    assert sorted((r.campaign_id, r.platform, r.status) for r in runs) == [
        (None, "linkedin", "error"),
        (None, "youtube", "error"),
    ]


@pytest.mark.asyncio
async def test_daily_job_warns_when_linkedin_token_is_close_to_expiring(
    db_session: AsyncSession, monkeypatch
):
    from jobs.platform_metrics_sync_core import sync_platform_metrics

    now = datetime(2026, 10, 20, tzinfo=timezone.utc)

    async def expires_soon(**_kwargs):
        return now + timedelta(days=5)

    async def skip(_db, **_kwargs):
        return social_posts.SourceSyncStats(platform="linkedin")

    _settings(monkeypatch, LINKEDIN_ADS_ACCESS_TOKEN="token")
    monkeypatch.setattr("services.social_posts.sync_linkedin_ads", skip)
    monkeypatch.setattr("jobs.platform_metrics_sync_core.linkedin_token_expires_at", expires_soon)

    stats = await sync_platform_metrics(db_session, platforms=["linkedin"], now=now)
    assert stats.linkedin_token_days_left == 5
    assert stats.linkedin_token_expiring is True


@pytest.mark.asyncio
async def test_daily_job_warns_on_refresh_token_expiry_when_renewal_is_on(
    db_session: AsyncSession, monkeypatch
):
    from jobs.platform_metrics_sync_core import sync_platform_metrics
    from services.connectors.linkedin_ads import LinkedInAccessToken

    now = datetime(2026, 10, 20, tzinfo=timezone.utc)

    async def refreshed(_settings, _integration):
        return "fresh", LinkedInAccessToken("fresh", now + timedelta(days=60), now + timedelta(days=8))

    async def never(**_kwargs):
        raise AssertionError("introspection is not needed when renewing")

    async def skip(_db, **_kwargs):
        return social_posts.SourceSyncStats(platform="linkedin")

    monkeypatch.setattr("services.social_posts.sync_linkedin_ads", skip)
    monkeypatch.setattr("jobs.platform_metrics_sync_core.linkedin_ads_access_token", refreshed)
    monkeypatch.setattr("jobs.platform_metrics_sync_core.linkedin_token_expires_at", never)

    stats = await sync_platform_metrics(db_session, platforms=["linkedin"], now=now)
    assert (stats.linkedin_token_days_left, stats.linkedin_token_expiring) == (8, True)
