"""CPR-15: platform sync outcomes, report-input statuses, and the daily job."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import api_headers
from models.campaign import PlatformSyncRun
from services.connectors import ConnectorError, FetchResult


async def _campaign(client: AsyncClient, name: str, platforms: list[str]) -> int:
    response = await client.post(
        "/api/admin/campaigns",
        headers=api_headers(),
        json={"name": name, "platforms": platforms},
    )
    return response.json()["id"]


async def _configure(client: AsyncClient, platform: str, **config) -> None:
    await client.patch(
        "/api/admin/integrations",
        headers=api_headers(),
        json={"platforms": {platform: {"enabled": True, **config}}},
    )


async def _runs(db: AsyncSession, campaign_id: int) -> list[str]:
    rows = (
        await db.execute(
            select(PlatformSyncRun.status).where(PlatformSyncRun.campaign_id == campaign_id)
        )
    ).scalars()
    return list(rows)


@pytest.mark.asyncio
async def test_unmapped_campaign_is_not_synced_or_counted_as_an_error(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    monkeypatch.setenv("YOUTUBE_API_KEY", "yt-key")
    from config import get_settings

    get_settings.cache_clear()
    campaign_id = await _campaign(client, "Unmapped YouTube", ["youtube"])

    sync = await client.post(
        f"/api/admin/campaigns/{campaign_id}/platforms/youtube/sync", headers=api_headers()
    )
    assert sync.status_code == 400
    assert "No YouTube posts linked" in sync.json()["message"]
    assert await _runs(db_session, campaign_id) == ["unmapped"]

    packet = await client.get(
        f"/api/campaigns/{campaign_id}/report-packet",
        headers=api_headers(),
        params={"sources": ["youtube"]},
    )
    assert packet.json()["inputCompleteness"]["youtube"]["status"] == "missing"


@pytest.mark.asyncio
async def test_failed_sync_shows_as_error_in_report_inputs(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    async def broken(**_kwargs):
        raise ConnectorError("LinkedIn Ads access token expired or invalid")

    monkeypatch.setattr("services.platform_data.fetch_linkedin_ads_metrics", broken)
    campaign_id = await _campaign(client, "Broken LinkedIn", ["linkedin"])
    await _configure(
        client, "linkedin", campaignMap={str(campaign_id): {"linkedinCampaignIds": ["1"]}}
    )

    sync = await client.post(
        f"/api/admin/campaigns/{campaign_id}/platforms/linkedin/sync", headers=api_headers()
    )
    assert sync.status_code == 502
    assert await _runs(db_session, campaign_id) == ["error"]

    packet = await client.get(
        f"/api/campaigns/{campaign_id}/report-packet",
        headers=api_headers(),
        params={"sources": ["linkedin"]},
    )
    linkedin = packet.json()["inputCompleteness"]["linkedin"]
    assert linkedin["status"] == "error"
    assert linkedin["fetchedAt"] is not None


async def _no_token_check(*_args, **_kwargs):
    return "token", None


@pytest.mark.asyncio
async def test_daily_job_syncs_mapped_linkedin_campaigns_and_skips_the_rest(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    from jobs.platform_metrics_sync_core import sync_platform_metrics

    synced: list[int] = []

    async def fake_linkedin(*, campaign_id, **_kwargs):
        synced.append(campaign_id)
        return FetchResult(rows=[{"campaign": "1", "impressions": "10"}], raw={"connector": "linkedin_ads"})

    monkeypatch.setattr("services.platform_data.fetch_linkedin_ads_metrics", fake_linkedin)
    monkeypatch.setattr("services.platform_data.linkedin_ads_access_token", _no_token_check)
    monkeypatch.setattr("jobs.platform_metrics_sync_core.linkedin_ads_access_token", _no_token_check)
    mapped = await _campaign(client, "Mapped LinkedIn", ["linkedin"])
    unmapped = await _campaign(client, "Unmapped LinkedIn 2", ["linkedin"])
    await _campaign(client, "CSV only", ["meta"])
    await _configure(client, "linkedin", campaignMap={str(mapped): {"linkedinCampaignIds": ["1"]}})

    stats = await sync_platform_metrics(db_session, campaign_ids=[mapped, unmapped], platforms=["linkedin"])

    assert synced == [mapped]
    assert (stats.campaigns, stats.synced, stats.unmapped, stats.errors) == (2, 1, 1, [])
    assert stats.youtube is None and stats.links is not None

    data = await client.get(f"/api/admin/campaigns/{mapped}/platform-data", headers=api_headers())
    linkedin = next(item for item in data.json()["items"] if item["platform"] == "linkedin")
    assert linkedin["status"] == "available"


@pytest.mark.asyncio
async def test_daily_job_dry_run_calls_nothing(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    from jobs.platform_metrics_sync_core import sync_platform_metrics

    async def fail(*_args, **_kwargs):
        raise AssertionError("dry run must not call the API")

    monkeypatch.setattr("services.platform_data.fetch_linkedin_ads_metrics", fail)
    monkeypatch.setattr("services.social_posts.sync_youtube", fail)
    monkeypatch.setattr("services.post_links.relink", fail)
    monkeypatch.setattr("jobs.platform_metrics_sync_core.linkedin_ads_access_token", fail)
    campaign_id = await _campaign(client, "Dry run", ["youtube", "linkedin"])

    stats = await sync_platform_metrics(
        db_session, campaign_ids=[campaign_id], platforms=["youtube", "linkedin"], dry_run=True
    )
    assert (stats.campaigns, stats.synced) == (1, 0)


@pytest.mark.asyncio
async def test_daily_job_warns_when_linkedin_token_is_close_to_expiring(
    db_session: AsyncSession, monkeypatch
):
    from jobs.platform_metrics_sync_core import sync_platform_metrics

    now = datetime(2026, 10, 20, tzinfo=timezone.utc)

    async def expires_soon(**_kwargs):
        return now + timedelta(days=5)

    monkeypatch.setenv("LINKEDIN_ADS_ACCESS_TOKEN", "token")
    from config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr("jobs.platform_metrics_sync_core.linkedin_token_expires_at", expires_soon)

    stats = await sync_platform_metrics(db_session, campaign_ids=[-1], platforms=["linkedin"], now=now)
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

    monkeypatch.setattr("jobs.platform_metrics_sync_core.linkedin_ads_access_token", refreshed)
    monkeypatch.setattr("jobs.platform_metrics_sync_core.linkedin_token_expires_at", never)

    stats = await sync_platform_metrics(db_session, campaign_ids=[-1], platforms=["linkedin"], now=now)
    assert (stats.linkedin_token_days_left, stats.linkedin_token_expiring) == (8, True)


@pytest.mark.asyncio
async def test_failed_sync_run_is_committed_before_the_error_response(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    # get_db rolls back when the HTTPException escapes, so the failed run must
    # already be committed by then.
    async def broken(**_kwargs):
        raise ConnectorError("LinkedIn Ads API error 500")

    monkeypatch.setattr("services.platform_data.fetch_linkedin_ads_metrics", broken)
    campaign_id = await _campaign(client, "Committed failure", ["linkedin"])
    await _configure(
        client, "linkedin", campaignMap={str(campaign_id): {"linkedinCampaignIds": ["1"]}}
    )

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
    assert committed == [["error"]]


@pytest.mark.asyncio
async def test_unmapped_linkedin_campaign_skips_the_token(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    async def broken_token(*_args):
        raise ConnectorError("LinkedIn Ads refresh token expired or revoked")

    monkeypatch.setattr("services.platform_data.linkedin_ads_access_token", broken_token)
    campaign_id = await _campaign(client, "Unmapped LinkedIn", ["linkedin"])
    await _configure(client, "linkedin")

    sync = await client.post(
        f"/api/admin/campaigns/{campaign_id}/platforms/linkedin/sync", headers=api_headers()
    )
    assert sync.status_code == 400
    assert await _runs(db_session, campaign_id) == ["unmapped"]


@pytest.mark.asyncio
async def test_disabled_connector_is_logged_as_not_enabled(
    client: AsyncClient, db_session: AsyncSession
):
    campaign_id = await _campaign(client, "Disabled LinkedIn", ["linkedin"])
    await client.patch(
        "/api/admin/integrations",
        headers=api_headers(),
        json={"platforms": {"linkedin": {"enabled": False}}},
    )

    sync = await client.post(
        f"/api/admin/campaigns/{campaign_id}/platforms/linkedin/sync", headers=api_headers()
    )
    assert sync.status_code == 400
    assert await _runs(db_session, campaign_id) == ["not_enabled"]

    packet = await client.get(
        f"/api/campaigns/{campaign_id}/report-packet",
        headers=api_headers(),
        params={"sources": ["linkedin"]},
    )
    assert packet.json()["inputCompleteness"]["linkedin"]["status"] == "missing"


@pytest.mark.asyncio
async def test_daily_job_logs_network_failures_and_moves_on(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    import httpx

    from jobs.platform_metrics_sync_core import sync_platform_metrics
    from services import social_posts
    from services.connectors.linkedin_ads import fetch_linkedin_ads_metrics

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    async def linkedin_offline(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(offline)) as http:
            return await fetch_linkedin_ads_metrics(**kwargs, client=http)

    monkeypatch.setattr("services.platform_data.fetch_linkedin_ads_metrics", linkedin_offline)
    monkeypatch.setattr("services.platform_data.linkedin_ads_access_token", _no_token_check)
    monkeypatch.setattr("jobs.platform_metrics_sync_core.linkedin_ads_access_token", _no_token_check)
    monkeypatch.setattr(
        social_posts, "_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(offline))
    )
    monkeypatch.setenv("YOUTUBE_API_KEY", "yt-key")
    from config import get_settings

    get_settings.cache_clear()
    first = await _campaign(client, "Offline 1", ["linkedin"])
    second = await _campaign(client, "Offline 2", ["linkedin"])
    await _configure(
        client,
        "linkedin",
        campaignMap={str(c): {"linkedinCampaignIds": ["1"]} for c in (first, second)},
    )

    stats = await sync_platform_metrics(
        db_session, campaign_ids=[first, second], platforms=["youtube", "linkedin"]
    )
    assert len(stats.errors) == 3
    assert stats.errors[0].startswith("youtube: YouTube playlistItems.list request failed")
    assert await _runs(db_session, first) == await _runs(db_session, second) == ["error"]
    youtube_run = (
        await db_session.execute(select(PlatformSyncRun).where(PlatformSyncRun.campaign_id.is_(None)))
    ).scalar_one()
    assert (youtube_run.platform, youtube_run.status) == ("youtube", "error")
