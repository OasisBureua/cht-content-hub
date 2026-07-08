"""Integration tests for public KOL HTTP routes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from conftest import API_KEY, api_headers


@pytest.mark.asyncio
async def test_root(http_client: AsyncClient):
    response = await http_client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "contenthub-api"
    assert body["public_api"] == "/api/public/kols"


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["info"]["app"]["status"] == "up"


@pytest.mark.asyncio
async def test_kols_requires_api_key(http_client: AsyncClient):
    response = await http_client.get("/api/public/kols")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "AUTH_INVALID_KEY"
    assert body["error"]["message"] == "Missing API key"
    assert body["error"]["status"] == 401
    assert body["error"]["request_id"]


@pytest.mark.asyncio
async def test_kols_rejects_invalid_api_key(http_client: AsyncClient):
    response = await http_client.get(
        "/api/public/kols",
        headers={"X-API-Key": "wrong-key"},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "AUTH_INVALID_KEY"
    assert body["error"]["message"] == "Invalid API key"
    assert body["error"]["status"] == 401


@pytest.mark.asyncio
async def test_kols_empty_list(client: AsyncClient):
    response = await client.get("/api/public/kols", headers=api_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["regions"] == []
    assert body["institutions"] == []


@pytest.mark.asyncio
async def test_kols_list_with_data(client: AsyncClient, sample_kol, kol_with_shoot):
    response = await client.get("/api/public/kols", headers=api_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    names = {item["name"] for item in body["items"]}
    assert names == {"Dr. Jane Smith", "Dr. Jason Mouabbi"}
    assert len(body["regions"]) == 2
    assert set(body["institutions"]) == {"MD Anderson", "UCSF"}


@pytest.mark.asyncio
async def test_kols_filter_by_region(client: AsyncClient, sample_kol, kol_with_shoot):
    response = await client.get(
        "/api/public/kols",
        headers=api_headers(),
        params={"region": "texas"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Dr. Jason Mouabbi"


@pytest.mark.asyncio
async def test_kols_search_query(client: AsyncClient, sample_kol, kol_with_shoot):
    response = await client.get(
        "/api/public/kols",
        headers=api_headers(),
        params={"q": "UCSF"},
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["institution"] == "UCSF"


@pytest.mark.asyncio
async def test_kols_new_only_filter(client: AsyncClient, kol_with_shoot):
    response = await client.get(
        "/api/public/kols",
        headers=api_headers(),
        params={"new_only": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["is_new"] is True


@pytest.mark.asyncio
async def test_kols_pagination(client: AsyncClient, sample_kol, kol_with_shoot):
    response = await client.get(
        "/api/public/kols",
        headers=api_headers(),
        params={"limit": 1, "offset": 1},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 1


@pytest.mark.asyncio
async def test_kols_omit_intel_by_default(client: AsyncClient, kol_with_publications):
    response = await client.get("/api/public/kols", headers=api_headers())
    assert response.status_code == 200
    item = next(
        i for i in response.json()["items"] if i["name"] == "Dr. Virginia Kaklamani"
    )
    assert item.get("intel") is None


@pytest.mark.asyncio
async def test_kol_detail(client: AsyncClient, kol_with_shoot):
    slug = kol_with_shoot.slug
    response = await client.get(
        f"/api/public/kols/{slug}",
        headers=api_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == slug
    assert body["shoot_count"] == 1
    assert body["region_label"] == "Texas"


@pytest.mark.asyncio
async def test_kol_detail_not_found(client: AsyncClient):
    response = await client.get(
        "/api/public/kols/unknown-slug",
        headers=api_headers(),
    )
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert body["error"]["message"] == "KOL not found"
    assert body["error"]["status"] == 404


@pytest.mark.asyncio
async def test_kol_publications_empty_without_npi(client: AsyncClient, sample_kol):
    slug = sample_kol.slug
    response = await client.get(
        f"/api/public/kols/{slug}/publications",
        headers=api_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_kol_publications_with_signals(client: AsyncClient, kol_with_publications):
    slug = kol_with_publications.slug
    response = await client.get(
        f"/api/public/kols/{slug}/publications",
        headers=api_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["items"][0]["title"] == "Recent Paper"
    assert body["items"][0]["journal"] == "JCO"


@pytest.mark.asyncio
async def test_app_has_rate_limiter():
    from main import app

    assert app.state.limiter is not None


@pytest.mark.asyncio
async def test_rate_limit_enforced(client: AsyncClient):
    headers = api_headers()
    for _ in range(100):
        response = await client.get("/api/public/kols", headers=headers)
        assert response.status_code == 200
    response = await client.get("/api/public/kols", headers=headers)
    assert response.status_code == 429
    body = response.json()
    assert body["error"]["code"] == "RATE_LIMITED"
    assert body["error"]["status"] == 429


@pytest.mark.asyncio
async def test_hcp_upsert_requires_api_key(http_client: AsyncClient):
    response = await http_client.post(
        "/api/public/hcp/upsert",
        json={"npi": "1234567890", "first_name": "Jane", "last_name": "Doe"},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "AUTH_INVALID_KEY"
    assert body["error"]["message"] == "Missing API key"


@pytest.mark.asyncio
async def test_hcp_upsert_creates(client: AsyncClient, db_session):
    from hcp_intel.models import HCP

    response = await client.post(
        "/api/public/hcp/upsert",
        headers=api_headers(),
        json={
            "npi": "9876543210",
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane@example.com",
            "specialty": "Medical Oncology",
            "city": "Houston",
            "state": "TX",
            "zip": "77030",
            "institution": "MD Anderson",
            "source": "cht",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {"created": True, "npi": "9876543210"}

    hcp = await db_session.get(HCP, "9876543210")
    assert hcp is not None
    assert hcp.taxonomy == "Medical Oncology"
    assert hcp.hospital_affiliations == "MD Anderson"
    assert hcp.source == "cht"


@pytest.mark.asyncio
async def test_hcp_upsert_updates_existing(client: AsyncClient, db_session):
    from hcp_intel.models import HCP

    db_session.add(
        HCP(
            npi="1111111111",
            first_name="Old",
            last_name="Name",
            taxonomy="Legacy",
            source="manual",
        )
    )
    await db_session.flush()

    response = await client.post(
        "/api/public/hcp/upsert",
        headers=api_headers(),
        json={
            "npi": "1111111111",
            "first_name": "New",
            "last_name": "Name",
            "specialty": "Cardiology",
            "source": "cht",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"created": False, "npi": "1111111111"}

    hcp = await db_session.get(HCP, "1111111111")
    assert hcp.first_name == "New"
    assert hcp.taxonomy == "Cardiology"
    assert hcp.source == "cht"


@pytest.mark.asyncio
async def test_hcp_upsert_rejects_invalid_npi(client: AsyncClient):
    response = await client.post(
        "/api/public/hcp/upsert",
        headers=api_headers(),
        json={"npi": "123", "first_name": "Jane", "last_name": "Doe"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "NPI must be exactly 10 digits"
    assert body["error"]["status"] == 422
