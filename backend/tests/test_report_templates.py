"""CPR-25: report template catalog pointer (semver + s3_key) and packet resolution."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from conftest import api_headers, mint_test_token

EXEC = "executive_summary"


def bearer(scopes: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_test_token(scopes)}"}


async def _create_template(client: AsyncClient, **fields) -> dict:
    payload = {"name": "Executive Summary", "type": EXEC, **fields}
    response = await client.post("/api/admin/templates", headers=api_headers(), json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def _create_campaign(client: AsyncClient, **fields) -> int:
    response = await client.post(
        "/api/admin/campaigns",
        headers=api_headers(),
        json={"name": "Template Campaign", **fields},
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


async def _packet(client: AsyncClient, campaign_id: int) -> dict:
    response = await client.get(
        f"/api/campaigns/{campaign_id}/report-packet", headers=api_headers()
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_create_template_with_s3_pointer(client: AsyncClient):
    body = await _create_template(
        client, semver="1.0.0", s3Key="templates/executive_summary/1.0.0/"
    )
    assert body["semver"] == "1.0.0"
    assert body["s3Key"] == "templates/executive_summary/1.0.0/"

    listed = (await client.get("/api/admin/templates", headers=api_headers())).json()
    assert any(t["id"] == body["id"] and t["s3Key"] for t in listed["items"])


@pytest.mark.asyncio
async def test_create_template_without_pointer_still_allowed(client: AsyncClient):
    body = await _create_template(client, type="analytics")
    assert body["semver"] is None
    assert body["s3Key"] is None


@pytest.mark.asyncio
async def test_create_template_rejects_bad_semver(client: AsyncClient):
    response = await client.post(
        "/api/admin/templates",
        headers=api_headers(),
        json={"name": "Bad", "type": EXEC, "semver": "v1", "s3Key": "x/"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_template_requires_semver_with_s3_key(client: AsyncClient):
    response = await client.post(
        "/api/admin/templates",
        headers=api_headers(),
        json={"name": "No version", "type": EXEC, "s3Key": "templates/x/"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_template_duplicate_version_conflicts(client: AsyncClient):
    await _create_template(client, semver="2.0.0", s3Key="templates/executive_summary/2.0.0/")
    response = await client.post(
        "/api/admin/templates",
        headers=api_headers(),
        json={
            "name": "Dup",
            "type": EXEC,
            "semver": "2.0.0",
            "s3Key": "templates/executive_summary/2.0.0/",
        },
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_packet_template_missing_when_no_catalog_row(client: AsyncClient):
    campaign_id = await _create_campaign(client)
    body = await _packet(client, campaign_id)
    assert body["template"] is None
    assert body["inputCompleteness"]["template"]["status"] == "missing"


@pytest.mark.asyncio
async def test_packet_uses_latest_executive_summary_by_semver(client: AsyncClient):
    await _create_template(client, semver="1.2.0", s3Key="templates/executive_summary/1.2.0/")
    await _create_template(client, semver="1.10.0", s3Key="templates/executive_summary/1.10.0/")
    await _create_template(client, semver="1.9.3", s3Key="templates/executive_summary/1.9.3/")
    campaign_id = await _create_campaign(client)

    body = await _packet(client, campaign_id)
    assert body["template"]["type"] == EXEC
    assert body["template"]["semver"] == "1.10.0"
    assert body["template"]["s3Key"] == "templates/executive_summary/1.10.0/"
    assert body["inputCompleteness"]["template"]["status"] == "ok"


@pytest.mark.asyncio
async def test_packet_prefers_campaign_linked_template(client: AsyncClient):
    await _create_template(client, semver="3.0.0", s3Key="templates/executive_summary/3.0.0/")
    pinned = await _create_template(
        client, semver="2.5.0", s3Key="templates/executive_summary/2.5.0/"
    )
    campaign_id = await _create_campaign(client, templateId=pinned["id"])

    body = await _packet(client, campaign_id)
    assert body["template"]["id"] == pinned["id"]
    assert body["template"]["semver"] == "2.5.0"


@pytest.mark.asyncio
async def test_packet_ignores_linked_template_without_body(client: AsyncClient):
    legacy = await _create_template(client, type="analytics")
    await _create_template(client, semver="4.0.0", s3Key="templates/executive_summary/4.0.0/")
    campaign_id = await _create_campaign(client, templateId=legacy["id"])

    body = await _packet(client, campaign_id)
    assert body["template"]["semver"] == "4.0.0"


@pytest.mark.asyncio
async def test_create_template_requires_admin_create_scope(client: AsyncClient):
    payload = {"name": "Scoped", "type": EXEC, "semver": "5.0.0", "s3Key": "templates/x/5.0.0/"}
    for scopes in ("hub/catalog.*", "hub/reports.*", "hub/admin.read"):
        response = await client.post("/api/admin/templates", headers=bearer(scopes), json=payload)
        assert response.status_code == 401, scopes
    response = await client.post(
        "/api/admin/templates", headers=bearer("hub/admin.create"), json=payload
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_packet_template_readable_with_reports_read_scope(client: AsyncClient):
    await _create_template(client, semver="6.0.0", s3Key="templates/executive_summary/6.0.0/")
    campaign_id = await _create_campaign(client)
    response = await client.get(
        f"/api/campaigns/{campaign_id}/report-packet", headers=bearer("hub/reports.read")
    )
    assert response.status_code == 200
    assert response.json()["template"]["semver"] == "6.0.0"

    response = await client.get(
        f"/api/campaigns/{campaign_id}/report-packet", headers={"X-API-Key": "test-public-key"}
    )
    assert response.status_code == 401
