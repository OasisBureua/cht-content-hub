"""Admin campaign API integration tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from conftest import api_headers
from models.campaign import CampaignPlatformData
from services.platform_data import utc_fetch_date


def admin_headers(**extra: str) -> dict[str, str]:
    return api_headers(**extra)


@pytest.mark.asyncio
async def test_admin_campaigns_require_api_key(http_client: AsyncClient):
    response = await http_client.get("/api/admin/campaigns")
    assert response.status_code == 401
    body = response.json()
    assert body["statusCode"] == 401
    assert body["error"] == "Unauthorized"


@pytest.mark.asyncio
async def test_campaign_crud(client: AsyncClient):
    create = await client.post(
        "/api/admin/campaigns",
        headers=admin_headers(),
        json={"name": "Q2 Breast Campaign", "clientSponsor": "PharmaCo"},
    )
    assert create.status_code == 201
    body = create.json()
    assert body["name"] == "Q2 Breast Campaign"
    assert body["clientSponsor"] == "PharmaCo"
    assert body["status"] == "draft"
    campaign_id = body["id"]

    listing = await client.get("/api/admin/campaigns", headers=admin_headers())
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    patch = await client.patch(
        f"/api/admin/campaigns/{campaign_id}",
        headers=admin_headers(),
        json={"status": "data_needed"},
    )
    assert patch.status_code == 200
    assert patch.json()["status"] == "data_needed"

    delete = await client.delete(
        f"/api/admin/campaigns/{campaign_id}",
        headers=admin_headers(),
    )
    assert delete.status_code == 204


@pytest.mark.asyncio
async def test_csv_upload_creates_platform_data(client: AsyncClient):
    create = await client.post(
        "/api/admin/campaigns",
        headers=admin_headers(),
        json={"name": "CSV Test", "platforms": ["linkedin"]},
    )
    campaign_id = create.json()["id"]

    upload = await client.post(
        f"/api/admin/campaigns/{campaign_id}/uploads",
        headers=admin_headers(),
        json={
            "platform": "linkedin",
            "filename": "li.csv",
            "content": "views,clicks\n100,10",
        },
    )
    assert upload.status_code == 201
    assert upload.json()["rowCount"] == 1
    assert upload.json()["fetchDate"] == utc_fetch_date().isoformat()

    platform_data = await client.get(
        f"/api/admin/campaigns/{campaign_id}/platform-data",
        headers=admin_headers(),
    )
    assert platform_data.status_code == 200
    items = platform_data.json()["items"]
    assert len(items) == 1
    assert items[0]["platform"] == "linkedin"
    assert items[0]["status"] == "available"
    assert items[0]["rowCount"] == 1
    assert items[0]["source"] == "csv"


@pytest.mark.asyncio
async def test_same_day_csv_refresh_updates_one_row(client: AsyncClient, db_session):
    create = await client.post(
        "/api/admin/campaigns",
        headers=admin_headers(),
        json={"name": "Same day", "platforms": ["linkedin"]},
    )
    campaign_id = create.json()["id"]

    await client.post(
        f"/api/admin/campaigns/{campaign_id}/uploads",
        headers=admin_headers(),
        json={
            "platform": "linkedin",
            "filename": "v1.csv",
            "content": "views,clicks\n100,10",
        },
    )
    await client.post(
        f"/api/admin/campaigns/{campaign_id}/uploads",
        headers=admin_headers(),
        json={
            "platform": "linkedin",
            "filename": "v2.csv",
            "content": "views,clicks\n200,20\n300,30",
        },
    )

    count = (
        await db_session.execute(
            select(func.count())
            .select_from(CampaignPlatformData)
            .where(CampaignPlatformData.campaign_id == campaign_id)
        )
    ).scalar()
    assert count == 1

    row = (
        await db_session.execute(
            select(CampaignPlatformData).where(
                CampaignPlatformData.campaign_id == campaign_id
            )
        )
    ).scalar_one()
    assert row.row_count == 2
    assert row.filename == "v2.csv"
    assert row.fetch_date == utc_fetch_date()


@pytest.mark.asyncio
async def test_new_day_csv_creates_second_row(client: AsyncClient, db_session):
    create = await client.post(
        "/api/admin/campaigns",
        headers=admin_headers(),
        json={"name": "New day", "platforms": ["linkedin"]},
    )
    campaign_id = create.json()["id"]

    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    old = CampaignPlatformData(
        campaign_id=campaign_id,
        platform="linkedin",
        fetch_date=utc_fetch_date(yesterday),
        status="available",
        synced_at=yesterday,
        row_count=1,
        rows=[{"views": "1"}],
        source="csv",
        filename="old.csv",
    )
    db_session.add(old)
    await db_session.flush()

    await client.post(
        f"/api/admin/campaigns/{campaign_id}/uploads",
        headers=admin_headers(),
        json={
            "platform": "linkedin",
            "filename": "today.csv",
            "content": "views,clicks\n500,50",
        },
    )

    rows = list(
        (
            await db_session.execute(
                select(CampaignPlatformData)
                .where(CampaignPlatformData.campaign_id == campaign_id)
                .order_by(CampaignPlatformData.fetch_date)
            )
        ).scalars()
    )
    assert len(rows) == 2
    assert rows[-1].filename == "today.csv"
    assert rows[-1].fetch_date == utc_fetch_date()


@pytest.mark.asyncio
async def test_validation_and_report_generate(client: AsyncClient):
    create = await client.post(
        "/api/admin/campaigns",
        headers=admin_headers(),
        json={"name": "Report Test", "platforms": ["youtube", "linkedin"]},
    )
    campaign_id = create.json()["id"]

    validation = await client.get(
        f"/api/admin/campaigns/{campaign_id}/validation",
        headers=admin_headers(),
    )
    assert validation.status_code == 200
    assert validation.json()["hubspotConnected"] is False
    assert len(validation.json()["dataSourcesSummary"]) == 6

    report = await client.post(
        f"/api/admin/campaigns/{campaign_id}/report/generate",
        headers=admin_headers(),
    )
    assert report.status_code == 200
    assert report.json()["campaign"]["id"] == campaign_id
    assert "sections" in report.json()


@pytest.mark.asyncio
async def test_hubspot_data_via_cht_patch(client: AsyncClient):
    create = await client.post(
        "/api/admin/campaigns",
        headers=admin_headers(),
        json={"name": "HubSpot via CHT", "hubspotCampaignId": "hs-123"},
    )
    campaign_id = create.json()["id"]

    patch = await client.patch(
        f"/api/admin/campaigns/{campaign_id}",
        headers=admin_headers(),
        json={
            "hubspotSyncedAt": "2026-06-25T21:00:00.000Z",
            "hubspotRawData": {"sessions": 1200, "source": "cht"},
        },
    )
    assert patch.status_code == 200

    report = await client.post(
        f"/api/admin/campaigns/{campaign_id}/report/generate",
        headers=admin_headers(),
    )
    assert report.json()["hubspotData"]["sessions"] == 1200


@pytest.mark.asyncio
async def test_platform_sync_requires_integration(client: AsyncClient):
    create = await client.post(
        "/api/admin/campaigns",
        headers=admin_headers(),
        json={"name": "Sync Test", "platforms": ["linkedin"]},
    )
    campaign_id = create.json()["id"]

    sync = await client.post(
        f"/api/admin/campaigns/{campaign_id}/platforms/linkedin/sync",
        headers=admin_headers(),
    )
    assert sync.status_code == 400

    await client.patch(
        "/api/admin/integrations",
        headers=admin_headers(),
        json={"platforms": {"linkedin": {"stub": True, "enabled": True}}},
    )

    sync = await client.post(
        f"/api/admin/campaigns/{campaign_id}/platforms/linkedin/sync",
        headers=admin_headers(),
    )
    assert sync.status_code == 200
    assert sync.json()["fetchDate"] == utc_fetch_date().isoformat()
