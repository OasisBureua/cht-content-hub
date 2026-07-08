"""Tests for LinkedIn Ads and YouTube platform connectors."""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from services.connectors.linkedin_ads import fetch_linkedin_ads_metrics
from services.connectors.youtube import fetch_youtube_metrics


@pytest.mark.asyncio
async def test_linkedin_ads_fetch_maps_metrics():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/adAnalytics")
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
                "linkedinCampaignIds": ["12345"],
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


@pytest.mark.asyncio
async def test_youtube_fetch_channel_videos_in_period():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/channels"):
            if "forHandle" in str(request.url):
                return httpx.Response(
                    200,
                    json={"items": [{"id": "UC123"}]},
                )
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "contentDetails": {
                                "relatedPlaylists": {"uploads": "UU123"}
                            }
                        }
                    ]
                },
            )
        if request.url.path.endswith("/playlistItems"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "snippet": {
                                "title": "Episode 1",
                                "publishedAt": "2026-06-15T12:00:00Z",
                                "resourceId": {"videoId": "vid1"},
                            }
                        }
                    ]
                },
            )
        if request.url.path.endswith("/videos"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "vid1",
                            "snippet": {
                                "title": "Episode 1",
                                "publishedAt": "2026-06-15T12:00:00Z",
                            },
                            "statistics": {"viewCount": "4200"},
                            "contentDetails": {"duration": "PT12M30S"},
                        }
                    ]
                },
            )
        raise AssertionError(f"unexpected path {request.url.path}")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await fetch_youtube_metrics(
            api_key="yt-key",
            channel_id="",
            channel_handle="@communityhealth",
            campaign_id=7,
            integration={},
            reporting_period_start=date(2026, 6, 1),
            reporting_period_end=date(2026, 6, 30),
            client=client,
        )

    assert "/youtube/v3/channels" in "".join(calls)
    assert len(result.rows) == 1
    assert result.rows[0]["views"] == "4200"
    assert result.rows[0]["average view duration"] == "12:30"


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
        headers={"X-API-Key": "test-public-key"},
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
        headers={"X-API-Key": "test-public-key"},
        json={"platforms": {"linkedin": {"enabled": True}}},
    )

    sync = await client.post(
        f"/api/admin/campaigns/{campaign_id}/platforms/linkedin/sync",
        headers={"X-API-Key": "test-public-key"},
    )
    assert sync.status_code == 200
    assert sync.json()["rowCount"] == 1

    platform_data = await client.get(
        f"/api/admin/campaigns/{campaign_id}/platform-data",
        headers={"X-API-Key": "test-public-key"},
    )
    linkedin = next(
        item for item in platform_data.json()["items"] if item["platform"] == "linkedin"
    )
    assert linkedin["status"] == "available"
    assert linkedin["rowCount"] == 1
