"""cht-reports' generate-time report-packet endpoint."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import api_headers
from models.shoot import Shoot


def admin_headers(**extra: str) -> dict[str, str]:
    return api_headers(**extra)


@pytest.mark.asyncio
async def test_report_packet_requires_api_key(http_client: AsyncClient):
    response = await http_client.get("/api/campaigns/1/report-packet")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_report_packet_404_for_missing_campaign(client: AsyncClient):
    response = await client.get(
        "/api/campaigns/999999/report-packet",
        headers=admin_headers(),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_report_packet_marks_missing_sources(client: AsyncClient):
    create = await client.post(
        "/api/admin/campaigns",
        headers=admin_headers(),
        json={"name": "Empty Campaign"},
    )
    campaign_id = create.json()["id"]

    response = await client.get(
        f"/api/campaigns/{campaign_id}/report-packet",
        headers=admin_headers(),
    )
    assert response.status_code == 200
    body = response.json()

    assert body["campaignId"] == campaign_id
    assert body["campaignName"] == "Empty Campaign"
    assert body["platformSlices"] == []
    assert body["sessions"] == []
    assert body["surveyResponses"] == []
    assert body["inputCompleteness"]["hubspot"]["status"] == "missing"
    assert body["inputCompleteness"]["sessions"]["status"] == "missing"
    assert body["inputCompleteness"]["surveyResponses"]["status"] == "missing"


@pytest.mark.asyncio
async def test_report_packet_includes_hubspot_data(client: AsyncClient):
    create = await client.post(
        "/api/admin/campaigns",
        headers=admin_headers(),
        json={"name": "HubSpot Campaign"},
    )
    campaign_id = create.json()["id"]

    await client.patch(
        f"/api/admin/campaigns/{campaign_id}",
        headers=admin_headers(),
        json={"hubspotRawData": {"opens": 42}},
    )

    response = await client.get(
        f"/api/campaigns/{campaign_id}/report-packet",
        headers=admin_headers(),
    )
    body = response.json()

    assert body["hubspotRawData"] == {"opens": 42}
    assert body["inputCompleteness"]["hubspot"]["status"] == "ok"


@pytest.mark.asyncio
async def test_report_packet_includes_linked_shoot_transcript(
    client: AsyncClient, db_session: AsyncSession
):
    create = await client.post(
        "/api/admin/campaigns",
        headers=admin_headers(),
        json={"name": "Shoot-Linked Campaign"},
    )
    campaign_id = create.json()["id"]

    shoot = Shoot(
        id="shoot-report-packet-1",
        name="Dr. Smith interview",
        campaign_id=campaign_id,
        shoot_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
        diarized_transcript="Dr. Smith [00:00]:\nHello and welcome.",
    )
    db_session.add(shoot)
    await db_session.commit()

    response = await client.get(
        f"/api/campaigns/{campaign_id}/report-packet",
        headers=admin_headers(),
    )
    body = response.json()

    assert len(body["sessions"]) == 1
    assert body["sessions"][0]["title"] == "Dr. Smith interview"
    assert body["sessions"][0]["transcriptText"] == "Dr. Smith [00:00]:\nHello and welcome."
    assert body["inputCompleteness"]["sessions"]["status"] == "ok"
    assert body["inputCompleteness"]["sessions"]["rowCount"] == 1


@pytest.mark.asyncio
async def test_report_packet_excludes_shoots_without_transcript(
    client: AsyncClient, db_session: AsyncSession
):
    create = await client.post(
        "/api/admin/campaigns",
        headers=admin_headers(),
        json={"name": "No-Transcript Campaign"},
    )
    campaign_id = create.json()["id"]

    shoot = Shoot(
        id="shoot-report-packet-2",
        name="Untranscribed shoot",
        campaign_id=campaign_id,
        diarized_transcript=None,
    )
    db_session.add(shoot)
    await db_session.commit()

    response = await client.get(
        f"/api/campaigns/{campaign_id}/report-packet",
        headers=admin_headers(),
    )
    body = response.json()

    assert body["sessions"] == []
    assert body["inputCompleteness"]["sessions"]["status"] == "missing"


@pytest.mark.asyncio
async def test_report_packet_excludes_shoots_linked_to_other_campaigns(
    client: AsyncClient, db_session: AsyncSession
):
    campaign_a = (
        await client.post(
            "/api/admin/campaigns",
            headers=admin_headers(),
            json={"name": "Campaign A"},
        )
    ).json()["id"]
    campaign_b = (
        await client.post(
            "/api/admin/campaigns",
            headers=admin_headers(),
            json={"name": "Campaign B"},
        )
    ).json()["id"]

    shoot = Shoot(
        id="shoot-report-packet-3",
        name="Belongs to campaign B",
        campaign_id=campaign_b,
        diarized_transcript="Transcript for B.",
    )
    db_session.add(shoot)
    await db_session.commit()

    response = await client.get(
        f"/api/campaigns/{campaign_a}/report-packet",
        headers=admin_headers(),
    )
    body = response.json()

    assert body["sessions"] == []


@pytest.mark.asyncio
async def test_report_packet_window_and_sources_passthrough(client: AsyncClient):
    create = await client.post(
        "/api/admin/campaigns",
        headers=admin_headers(),
        json={"name": "Window Campaign"},
    )
    campaign_id = create.json()["id"]

    response = await client.get(
        f"/api/campaigns/{campaign_id}/report-packet",
        headers=admin_headers(),
        params={
            "windowStart": "2026-08-01",
            "windowEnd": "2026-08-31",
            "sources": ["linkedin", "hubspot"],
        },
    )
    body = response.json()

    assert body["windowStart"] == "2026-08-01"
    assert body["windowEnd"] == "2026-08-31"
    assert body["sources"] == ["linkedin", "hubspot"]
