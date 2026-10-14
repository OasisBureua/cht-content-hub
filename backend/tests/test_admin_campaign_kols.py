"""CPR-45: KOLs attached to a campaign feed the report packet."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import api_headers
from models.kol import KOL


async def _campaign(client: AsyncClient, name: str) -> int:
    response = await client.post("/api/admin/campaigns", headers=api_headers(), json={"name": name})
    return response.json()["id"]


async def _kol(db: AsyncSession, slug: str, name: str, title: str, institution: str) -> KOL:
    kol = KOL(slug=slug, name=name, title=title, institution=institution)
    db.add(kol)
    await db.flush()
    return kol


@pytest.mark.asyncio
async def test_set_and_list_campaign_kols(client: AsyncClient, db_session: AsyncSession):
    campaign_id = await _campaign(client, "Zoom Webinar Campaign")
    kol_b = await _kol(db_session, "dr-b-ck", "Dr. B", "MD", "Mayo")
    kol_a = await _kol(db_session, "dr-a-ck", "Dr. A", "PhD", "UCSF")
    await db_session.commit()

    put = await client.put(
        f"/api/admin/campaigns/{campaign_id}/kols",
        headers=api_headers(),
        json={"kolIds": [kol_b.id, kol_a.id, kol_b.id]},
    )
    assert put.status_code == 200
    assert [k["name"] for k in put.json()["items"]] == ["Dr. A", "Dr. B"]

    listed = await client.get(f"/api/admin/campaigns/{campaign_id}/kols", headers=api_headers())
    assert listed.json()["items"][0] == {
        "id": kol_a.id,
        "slug": "dr-a-ck",
        "name": "Dr. A",
        "title": "PhD",
        "institution": "UCSF",
    }

    cleared = await client.put(
        f"/api/admin/campaigns/{campaign_id}/kols", headers=api_headers(), json={"kolIds": []}
    )
    assert cleared.json()["items"] == []


@pytest.mark.asyncio
async def test_set_campaign_kols_rejects_unknown_ids_and_missing_campaign(
    client: AsyncClient, db_session: AsyncSession
):
    campaign_id = await _campaign(client, "Unknown KOL Campaign")

    unknown = await client.put(
        f"/api/admin/campaigns/{campaign_id}/kols",
        headers=api_headers(),
        json={"kolIds": ["00000000-0000-0000-0000-000000000000"]},
    )
    assert unknown.status_code == 422

    missing = await client.get("/api/admin/campaigns/999999/kols", headers=api_headers())
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_campaign_kols_require_admin_auth(http_client: AsyncClient):
    response = await http_client.get("/api/admin/campaigns/1/kols")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_report_packet_includes_attached_kols(client: AsyncClient, db_session: AsyncSession):
    campaign_id = await _campaign(client, "Packet KOL Campaign")
    kol = await _kol(db_session, "dr-c-ck", "Dr. C", "MD", "Dana-Farber")
    await db_session.commit()
    await client.put(
        f"/api/admin/campaigns/{campaign_id}/kols", headers=api_headers(), json={"kolIds": [kol.id]}
    )

    packet = await client.get(f"/api/campaigns/{campaign_id}/report-packet", headers=api_headers())

    assert packet.status_code == 200
    assert packet.json()["kols"] == [{"name": "Dr. C", "title": "MD", "institution": "Dana-Farber"}]
