"""Tests for LinkedIn Ads and YouTube platform connectors."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from conftest import api_headers
from services.connectors import ConnectorError
from services.connectors.linkedin_ads import (
    fetch_creative_days,
    linkedin_token_expires_at,
    list_ad_campaigns,
    list_creatives,
    normalize_post_urn,
)
from services.connectors.youtube import duration_seconds, fetch_videos, uploads_playlist_id


@pytest.mark.asyncio
async def test_linkedin_lists_campaigns_and_creatives_across_pages():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert request.headers["LinkedIn-Version"] == "202610"
        if request.url.path.endswith("/adCampaigns"):
            return httpx.Response(200, json={"elements": [
                {"id": 111, "name": "RIG-26-02_VEP_SPL2 | Boost", "status": "ACTIVE", "type": "SPONSORED_UPDATES"},
            ]})
        assert request.url.path == "/rest/adAccounts/515103342/creatives"
        if "pageToken" not in request.url.params:
            return httpx.Response(200, json={
                "elements": [
                    {"id": "urn:li:sponsoredCreative:1", "campaign": "urn:li:sponsoredCampaign:111",
                     "content": {"reference": "urn:li:share:7001"}, "intendedStatus": "ACTIVE",
                     "createdAt": 1760000000000, "name": "Boost 1"},
                ],
                "metadata": {"nextPageToken": "abc=="},
            })
        assert request.url.params["pageToken"] == "abc=="
        return httpx.Response(200, json={"elements": [
            {"id": "urn:li:sponsoredCreative:2", "campaign": "urn:li:sponsoredCampaign:111",
             "content": {"videoAd": {"reference": "urn:li:ugcPost:7002",
                                     "contentAuthor": "urn:li:organization:99345473"}},
             "intendedStatus": "PAUSED"},
            {"id": "urn:li:sponsoredCreative:3", "campaign": "urn:li:sponsoredCampaign:111",
             "content": {"textAd": {"headline": "Register now", "landingPage": "https://x"}}},
            {"id": "urn:li:sponsoredCreative:4", "campaign": "urn:li:sponsoredCampaign:111",
             "content": {"standardUpdateAd": {"reference": "urn:li:share:7004"}}},
            {"id": "urn:li:sponsoredCreative:5", "campaign": "urn:li:sponsoredCampaign:111",
             "content": {"spotlight": {"headline": "Follow us", "landingPage": "https://x"}}},
        ], "metadata": {}})

    api = dict(access_token="t", ad_account_id="515103342", api_version="202610")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        campaigns = await list_ad_campaigns(**api, client=client)
        creatives = await list_creatives(**api, client=client)

    assert [(c.id, c.name) for c in campaigns] == [("111", "RIG-26-02_VEP_SPL2 | Boost")]
    assert [(c.urn, c.campaign_id, c.reference, c.content_type, c.name) for c in creatives] == [
        ("urn:li:sponsoredCreative:1", "111", "urn:li:share:7001", "reference", "Boost 1"),
        ("urn:li:sponsoredCreative:2", "111", "urn:li:ugcPost:7002", "videoAd", ""),
        ("urn:li:sponsoredCreative:3", "111", None, "textAd", "Register now"),
        ("urn:li:sponsoredCreative:4", "111", "urn:li:share:7004", "standardUpdateAd", ""),
        ("urn:li:sponsoredCreative:5", "111", None, "spotlight", ""),
    ]
    assert creatives[0].created_at == datetime.fromtimestamp(1760000000, tz=timezone.utc)
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_linkedin_creative_days_reads_daily_metrics_with_quartiles():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        assert "pivot=CREATIVE" in url and "timeGranularity=DAILY" in url
        assert "creatives=List(urn%3Ali%3AsponsoredCreative%3A1)" in url
        assert "dateRange=(start:(year:2026,month:10,day:16),end:(year:2026,month:10,day:23))" in url
        assert "videoFirstQuartileCompletions" in request.url.params["fields"]
        return httpx.Response(200, json={"elements": [{
            "pivotValues": ["urn:li:sponsoredCreative:1"],
            "dateRange": {"start": {"year": 2026, "month": 10, "day": 20}, "end": {"year": 2026, "month": 10, "day": 20}},
            "impressions": 900, "clicks": 12, "videoViews": 300, "videoFirstQuartileCompletions": 200,
            "videoCompletions": 50, "costInLocalCurrency": "42.5",
        }]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        days = await fetch_creative_days(
            access_token="t", creative_urns=["urn:li:sponsoredCreative:1"],
            start=date(2026, 10, 16), end=date(2026, 10, 23), api_version="202610", client=client,
        )
    assert len(days) == 1
    assert (days[0].creative_urn, days[0].day) == ("urn:li:sponsoredCreative:1", date(2026, 10, 20))
    assert days[0].metrics["impressions"] == 900
    assert days[0].metrics["video_25"] == 200
    assert days[0].metrics["cost"] == 42.5
    assert days[0].metrics["reactions"] == 0


@pytest.mark.asyncio
async def test_linkedin_expired_token_is_a_clear_error():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"message": "expired"}))
    ) as client:
        with pytest.raises(ConnectorError, match="expired or invalid"):
            await list_creatives(access_token="t", ad_account_id="1", api_version="202610", client=client)


def test_normalize_post_urn():
    assert normalize_post_urn("urn:li:share:7001") == "urn:li:share:7001"
    assert normalize_post_urn("https://www.linkedin.com/feed/update/urn:li:activity:7003/") == "urn:li:activity:7003"
    assert normalize_post_urn("https://www.linkedin.com/feed/update/urn%3Ali%3AugcPost%3A7002") == "urn:li:ugcPost:7002"
    assert normalize_post_urn("urn:li:sponsoredCreative:1") is None
    assert normalize_post_urn(None) is None


@pytest.mark.asyncio
async def test_youtube_fetch_videos_reads_details_and_lifetime_counts():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/videos")
        assert request.url.params["id"] == "vid1,gone"
        # The API key stays out of the (logged) URL.
        assert "key" not in request.url.params
        assert request.headers["X-Goog-Api-Key"] == "yt-key"
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

    li = dict(access_token="t", ad_account_id="999", api_version="202610")
    yt = dict(api_key="secret-yt-key", video_ids=["v1"])
    from services.connectors.linkedin_ads import refresh_linkedin_access_token

    for handler, match in ((offline, "request failed"), (not_json, "invalid JSON")):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ConnectorError, match=match) as yt_error:
                await fetch_videos(**yt, client=client)
            assert "secret-yt-key" not in str(yt_error.value)
            with pytest.raises(ConnectorError, match=match):
                await list_creatives(**li, client=client)
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
