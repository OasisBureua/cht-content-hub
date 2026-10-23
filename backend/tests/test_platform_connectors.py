"""Tests for LinkedIn Ads and YouTube platform connectors."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from conftest import api_headers
from services.connectors import ConnectorError, ConnectorNoData, ConnectorNotMapped
from services.connectors.linkedin_ads import (
    fetch_linkedin_ads_metrics,
    linkedin_token_expires_at,
)
from services.connectors.youtube import duration_seconds, fetch_videos, uploads_playlist_id


@pytest.mark.asyncio
async def test_linkedin_ads_fetch_maps_metrics():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/adAnalytics")
        assert request.headers["LinkedIn-Version"] == "202610"
        assert "campaigns=List(urn%3Ali%3AsponsoredCampaign%3A12345)" in str(request.url)
        assert "accounts=" not in str(request.url)
        assert "dateRange=(start:(year:2026,month:6,day:1),end:(year:2026,month:6,day:30))" in str(request.url)
        assert "totalEngagements" in request.url.params["fields"]
        return httpx.Response(
            200,
            json={
                "elements": [
                    {
                        "impressions": 1000,
                        "clicks": 40,
                        "videoViews": 200,
                        "videoCompletions": 50,
                        "averageDwellTime": 3.5,
                        "reactions": 12,
                        "costInLocalCurrency": "19.5",
                        "pivotValues": ["urn:li:sponsoredCampaign:12345"],
                        "dateRange": {
                            "start": {"year": 2026, "month": 6, "day": 1},
                            "end": {"year": 2026, "month": 6, "day": 1},
                        },
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await fetch_linkedin_ads_metrics(
            access_token="test-token",
            ad_account_id="999",
            campaign_id=1,
            integration={
                "campaignMap": {"1": {"linkedinCampaignIds": ["12345"]}},
            },
            reporting_period_start=date(2026, 6, 1),
            reporting_period_end=date(2026, 6, 30),
            client=client,
        )

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row["impressions"] == "1000"
    assert row["video views"] == "200"
    assert row["completion rate"] == "0.25"
    assert row["dwell time"] == "3.5"
    assert row["reactions"] == "12"
    assert row["cost"] == "19.50"
    assert row["date"] == "2026-06-01"


@pytest.mark.asyncio
async def test_youtube_fetch_videos_reads_details_and_lifetime_counts():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/videos")
        assert request.url.params["id"] == "vid1,gone"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "vid1",
                        "snippet": {
                            "title": "Episode 1",
                            "description": "RIG-26-02_VEP_SPL2",
                            "publishedAt": "2026-06-15T12:00:00Z",
                            "channelId": "UCabc",
                            "channelTitle": "Oncology Exchange",
                            "thumbnails": {"high": {"url": "https://i.ytimg.com/vi/vid1/hq.jpg"}},
                        },
                        "statistics": {"viewCount": "4200", "likeCount": "31", "commentCount": "4"},
                        "contentDetails": {"duration": "PT12M30S"},
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        videos = await fetch_videos(api_key="yt-key", video_ids=["vid1", "gone", "vid1"], client=client)

    assert len(videos) == 1
    video = videos[0]
    assert (video.video_id, video.channel_id, video.views, video.likes, video.comments) == (
        "vid1",
        "UCabc",
        4200,
        31,
        4,
    )
    assert video.duration_seconds == 750
    assert video.published_at == datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    assert video.url == "https://www.youtube.com/watch?v=vid1"


def test_youtube_durations_and_uploads_playlist():
    assert duration_seconds("PT1H2M3S") == 3723
    assert duration_seconds("P0D") == 0
    assert duration_seconds("") is None
    assert uploads_playlist_id("UCCB0N8VIIexXP10t_HDabQA") == "UUCB0N8VIIexXP10t_HDabQA"
    with pytest.raises(ConnectorError):
        uploads_playlist_id("PL123")


@pytest.mark.asyncio
async def test_linkedin_never_falls_back_to_the_ad_account():
    def fail(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"no API call expected, got {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(ConnectorNotMapped):
            await fetch_linkedin_ads_metrics(
                access_token="t",
                ad_account_id="999",
                campaign_id=7,
                integration={"linkedinCampaignIds": ["global"]},
                reporting_period_start=None,
                reporting_period_end=None,
                client=client,
            )


@pytest.mark.asyncio
async def test_connectors_report_no_data_and_expired_tokens():
    def empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"elements": [], "items": []})

    def expired(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "expired"})

    li = dict(
        access_token="t",
        ad_account_id="999",
        campaign_id=7,
        integration={"campaignMap": {"7": {"linkedinCampaignIds": ["1"]}}},
        reporting_period_start=date(2026, 6, 1),
        reporting_period_end=date(2026, 6, 30),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(empty)) as client:
        with pytest.raises(ConnectorNoData):
            await fetch_linkedin_ads_metrics(**li, client=client)
    async with httpx.AsyncClient(transport=httpx.MockTransport(expired)) as client:
        with pytest.raises(ConnectorError, match="expired or invalid"):
            await fetch_linkedin_ads_metrics(**li, client=client)


@pytest.mark.asyncio
async def test_linkedin_token_expiry_from_introspection():
    expires = int((datetime.now(timezone.utc) + timedelta(days=5)).timestamp())

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/oauth/v2/introspectToken"
        return httpx.Response(200, json={"active": True, "expires_at": expires})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        when = await linkedin_token_expires_at(
            access_token="t", client_id="id", client_secret="secret", client=client
        )
    assert when == datetime.fromtimestamp(expires, tz=timezone.utc)
    assert await linkedin_token_expires_at(access_token="t", client_id="", client_secret="") is None


@pytest.mark.asyncio
async def test_platform_sync_live_linkedin(client, monkeypatch):
    from services.connectors import FetchResult

    async def fake_fetch(**_kwargs):
        return FetchResult(
            rows=[
                {
                    "impressions": "500",
                    "video views": "120",
                    "clicks": "10",
                }
            ],
            raw={"connector": "linkedin_ads", "elementCount": 1},
        )

    monkeypatch.setenv("LINKEDIN_ADS_ACCESS_TOKEN", "token")
    monkeypatch.setenv("LINKEDIN_AD_ACCOUNT_ID", "123456")
    from config import get_settings

    get_settings.cache_clear()

    monkeypatch.setattr(
        "services.platform_data.fetch_linkedin_ads_metrics",
        fake_fetch,
    )

    create = await client.post(
        "/api/admin/campaigns",
        headers=api_headers(),
        json={
            "name": "Live LinkedIn",
            "platforms": ["linkedin"],
            "reportingPeriodStart": "2026-06-01",
            "reportingPeriodEnd": "2026-06-30",
        },
    )
    campaign_id = create.json()["id"]

    await client.patch(
        "/api/admin/integrations",
        headers=api_headers(),
        json={
            "platforms": {
                "linkedin": {
                    "enabled": True,
                    "campaignMap": {str(campaign_id): {"linkedinCampaignIds": ["1"]}},
                }
            }
        },
    )

    sync = await client.post(
        f"/api/admin/campaigns/{campaign_id}/platforms/linkedin/sync",
        headers=api_headers(),
    )
    assert sync.status_code == 200
    assert sync.json()["rowCount"] == 1

    platform_data = await client.get(
        f"/api/admin/campaigns/{campaign_id}/platform-data",
        headers=api_headers(),
    )
    linkedin = next(
        item for item in platform_data.json()["items"] if item["platform"] == "linkedin"
    )
    assert linkedin["status"] == "available"
    assert linkedin["rowCount"] == 1


@pytest.mark.asyncio
async def test_linkedin_refresh_returns_new_token_and_both_expiries():
    from services.connectors.linkedin_ads import refresh_linkedin_access_token

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/oauth/v2/accessToken"
        assert b"grant_type=refresh_token" in request.content
        return httpx.Response(
            200,
            json={"access_token": "fresh", "expires_in": 5184000, "refresh_token_expires_in": 31536000},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        token = await refresh_linkedin_access_token(
            refresh_token="r", client_id="id", client_secret="s", client=client
        )
    now = datetime.now(timezone.utc)
    assert token.access_token == "fresh"
    assert 59 <= (token.expires_at - now).days <= 60
    assert 364 <= (token.refresh_expires_at - now).days <= 365

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(400, json={"error": "invalid_grant"}))
    ) as client:
        with pytest.raises(ConnectorError, match="refresh token expired or revoked"):
            await refresh_linkedin_access_token(
                refresh_token="r", client_id="id", client_secret="s", client=client
            )


@pytest.mark.asyncio
async def test_linkedin_token_provider_refreshes_once_then_reuses(monkeypatch):
    from config import Settings
    from services.connectors import linkedin_auth
    from services.connectors.linkedin_ads import LinkedInAccessToken

    calls: list[str] = []

    async def fake_refresh(**kwargs):
        calls.append(kwargs["refresh_token"])
        now = datetime.now(timezone.utc)
        return LinkedInAccessToken("fresh", now + timedelta(days=60), now + timedelta(days=365))

    monkeypatch.setattr(linkedin_auth, "refresh_linkedin_access_token", fake_refresh)
    monkeypatch.setattr(linkedin_auth, "_refreshed", {})
    with_refresh = Settings(
        LINKEDIN_ADS_REFRESH_TOKEN="r1",
        LINKEDIN_ADS_CLIENT_ID="id",
        LINKEDIN_ADS_CLIENT_SECRET="s",
        LINKEDIN_ADS_ACCESS_TOKEN="static",
    )

    first, refreshed = await linkedin_auth.linkedin_ads_access_token(with_refresh, {})
    second, _ = await linkedin_auth.linkedin_ads_access_token(with_refresh, {})
    assert (first, second, calls) == ("fresh", "fresh", ["r1"])
    assert refreshed is not None

    static_only = Settings(LINKEDIN_ADS_ACCESS_TOKEN="static")
    assert await linkedin_auth.linkedin_ads_access_token(static_only, {}) == ("static", None)
    assert await linkedin_auth.linkedin_ads_access_token(static_only, {"accessToken": "cfg"}) == ("cfg", None)


@pytest.mark.asyncio
async def test_connectors_turn_network_and_json_failures_into_connector_errors():
    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    def not_json(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>maintenance</html>")

    li = dict(
        access_token="t",
        ad_account_id="999",
        campaign_id=7,
        integration={"campaignMap": {"7": {"linkedinCampaignIds": ["1"]}}},
        reporting_period_start=date(2026, 6, 1),
        reporting_period_end=date(2026, 6, 30),
    )
    yt = dict(api_key="secret-yt-key", video_ids=["v1"])
    from services.connectors.linkedin_ads import refresh_linkedin_access_token

    for handler, match in ((offline, "request failed"), (not_json, "invalid JSON")):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ConnectorError, match=match) as yt_error:
                await fetch_videos(**yt, client=client)
            assert "secret-yt-key" not in str(yt_error.value)
            with pytest.raises(ConnectorError, match=match):
                await fetch_linkedin_ads_metrics(**li, client=client)
            with pytest.raises(ConnectorError, match=match):
                await linkedin_token_expires_at(
                    access_token="t", client_id="id", client_secret="s", client=client
                )
            with pytest.raises(ConnectorError, match=match):
                await refresh_linkedin_access_token(
                    refresh_token="r", client_id="id", client_secret="s", client=client
                )


@pytest.mark.asyncio
async def test_linkedin_token_provider_does_not_retry_a_failed_refresh(monkeypatch):
    from config import Settings
    from services.connectors import linkedin_auth

    calls: list[str] = []

    async def revoked(**kwargs):
        calls.append(kwargs["refresh_token"])
        raise ConnectorError("LinkedIn Ads refresh token expired or revoked")

    monkeypatch.setattr(linkedin_auth, "refresh_linkedin_access_token", revoked)
    monkeypatch.setattr(linkedin_auth, "_refreshed", {})
    monkeypatch.setattr(linkedin_auth, "_failed", {})
    settings = Settings(
        LINKEDIN_ADS_REFRESH_TOKEN="r1", LINKEDIN_ADS_CLIENT_ID="id", LINKEDIN_ADS_CLIENT_SECRET="s"
    )

    for _ in range(3):
        with pytest.raises(ConnectorError, match="expired or revoked"):
            await linkedin_auth.linkedin_ads_access_token(settings, {})
    assert calls == ["r1"]
