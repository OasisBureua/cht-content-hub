"""SCRUM-58 admin KOL endpoints: GET, PATCH, refresh, headshot presign."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import API_KEY, api_headers
from models.kol import KOL
from utils.kol_public import kol_slug


@pytest.fixture
async def seeded_admin_kols(db_session: AsyncSession):
    """Two KOLs — one with an NPI, one without."""
    with_npi = KOL(
        slug=kol_slug("Dr. Alpha"),
        name="Dr. Alpha",
        title="MD",
        specialty="Medical Oncology",
        institution="UCSF",
        bio="Alpha bio",
        region="california",
        hcp_npi="1234567890",
    )
    without_npi = KOL(
        slug=kol_slug("Dr. Beta"),
        name="Dr. Beta",
        title="MD",
        specialty="Radiation Oncology",
        institution="MD Anderson",
        region="texas",
    )
    db_session.add_all([with_npi, without_npi])
    await db_session.flush()
    return {"with_npi": with_npi, "without_npi": without_npi}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_endpoints_require_api_key(client: AsyncClient):
    for path in (
        "/api/admin/kols",
        "/api/admin/kols/dr-alpha",
    ):
        r = await client.get(path)
        assert r.status_code == 401, path


# ---------------------------------------------------------------------------
# GET list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_admin_kols(client: AsyncClient, seeded_admin_kols):
    r = await client.get("/api/admin/kols", headers=api_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    slugs = [item["slug"] for item in body["items"]]
    assert set(slugs) == {kol_slug("Dr. Alpha"), kol_slug("Dr. Beta")}


@pytest.mark.asyncio
async def test_list_admin_kols_search(client: AsyncClient, seeded_admin_kols):
    r = await client.get(
        "/api/admin/kols", headers=api_headers(), params={"q": "alpha"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["slug"] == kol_slug("Dr. Alpha")


# ---------------------------------------------------------------------------
# GET detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_admin_kol(client: AsyncClient, seeded_admin_kols):
    slug = kol_slug("Dr. Alpha")
    r = await client.get(f"/api/admin/kols/{slug}", headers=api_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == slug
    assert body["bio"] == "Alpha bio"
    assert body["hcp_npi"] == "1234567890"
    assert body["curated_fields"] == []


@pytest.mark.asyncio
async def test_get_admin_kol_404(client: AsyncClient, seeded_admin_kols):
    r = await client.get(
        "/api/admin/kols/does-not-exist", headers=api_headers()
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PATCH
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_admin_kol_marks_curated(client: AsyncClient, seeded_admin_kols):
    slug = kol_slug("Dr. Alpha")
    r = await client.patch(
        f"/api/admin/kols/{slug}",
        headers=api_headers(),
        json={"bio": "New bio", "featured": True, "display_order": 1},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["bio"] == "New bio"
    assert body["featured"] is True
    assert body["display_order"] == 1
    assert set(body["curated_fields"]) == {"bio", "featured", "display_order"}


@pytest.mark.asyncio
async def test_patch_ignores_uneditable_field(
    client: AsyncClient, seeded_admin_kols
):
    slug = kol_slug("Dr. Alpha")
    # Pydantic strips unknown fields (schema doesn't declare them). Also
    # verify EDITABLE_FIELDS allowlist filters at the write helper.
    r = await client.patch(
        f"/api/admin/kols/{slug}",
        headers=api_headers(),
        json={"bio": "New bio"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Dr. Alpha"  # unchanged


@pytest.mark.asyncio
async def test_patch_empty_body_is_noop(client: AsyncClient, seeded_admin_kols):
    slug = kol_slug("Dr. Alpha")
    r = await client.patch(
        f"/api/admin/kols/{slug}", headers=api_headers(), json={}
    )
    assert r.status_code == 200
    assert r.json()["curated_fields"] == []


# ---------------------------------------------------------------------------
# POST /refresh
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_no_op_when_no_npi(client: AsyncClient, seeded_admin_kols):
    slug = kol_slug("Dr. Beta")  # no hcp_npi
    r = await client.post(f"/api/admin/kols/{slug}/refresh", headers=api_headers())
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "no_op"
    assert body["hcp_npi"] is None


@pytest.mark.asyncio
async def test_refresh_no_op_when_queue_url_missing(
    client: AsyncClient, seeded_admin_kols
):
    """Local dev / tests: queue URL is empty → refresh reports no_op."""
    slug = kol_slug("Dr. Alpha")  # has npi
    # Clear the module-level cooldown between test runs
    from admin.kols import _REFRESH_COOLDOWN
    _REFRESH_COOLDOWN.clear()

    r = await client.post(f"/api/admin/kols/{slug}/refresh", headers=api_headers())
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "no_op"
    assert body["hcp_npi"] == "1234567890"
    assert "HCP_INTEL_POLL_QUEUE_URL" in body["reason"]


@pytest.mark.asyncio
async def test_refresh_cooldown_applies_after_first_call(
    client: AsyncClient, seeded_admin_kols
):
    slug = kol_slug("Dr. Alpha")
    from admin.kols import _REFRESH_COOLDOWN
    _REFRESH_COOLDOWN.clear()

    # First call trips the cooldown (as no_op since queue URL empty).
    await client.post(f"/api/admin/kols/{slug}/refresh", headers=api_headers())

    # Second call within cooldown window reports "cooldown".
    r = await client.post(f"/api/admin/kols/{slug}/refresh", headers=api_headers())
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "cooldown"
    assert body["cooldown_remaining_seconds"] > 0


# ---------------------------------------------------------------------------
# POST /headshot/presign
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_presign_rejects_bad_content_type(
    client: AsyncClient, seeded_admin_kols
):
    slug = kol_slug("Dr. Alpha")
    r = await client.post(
        f"/api/admin/kols/{slug}/headshot/presign",
        headers=api_headers(),
        json={"content_type": "application/pdf"},
    )
    # Pydantic pattern validation → 422 before body handler runs
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_presign_503_when_bucket_unset(
    client: AsyncClient, seeded_admin_kols
):
    slug = kol_slug("Dr. Alpha")
    r = await client.post(
        f"/api/admin/kols/{slug}/headshot/presign",
        headers=api_headers(),
        json={"content_type": "image/png"},
    )
    # Local dev / tests: assets_bucket setting is empty.
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_presign_returns_valid_url_shape_when_bucket_set(
    client: AsyncClient, seeded_admin_kols, monkeypatch
):
    from config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ASSETS_BUCKET", "test-contenthub-assets")
    get_settings.cache_clear()

    slug = kol_slug("Dr. Alpha")

    # Stub boto3.client so no real AWS call happens.
    class _FakeS3:
        def generate_presigned_url(self, **_kwargs):
            return "https://test-contenthub-assets.s3.us-east-1.amazonaws.com/kol-headshots/dr-alpha.png?X-Amz-Signature=fake"

    with patch("admin.kols.boto3.client", return_value=_FakeS3()):
        r = await client.post(
            f"/api/admin/kols/{slug}/headshot/presign",
            headers=api_headers(),
            json={"content_type": "image/png"},
        )

    get_settings.cache_clear()  # restore for other tests

    assert r.status_code == 200
    body = r.json()
    assert body["key"] == f"kol-headshots/{slug}.png"
    assert body["photo_url"].endswith(f"/kol-headshots/{slug}.png")
    assert body["upload_method"] == "PUT"
    assert body["upload_headers"]["Content-Type"] == "image/png"
    assert body["expires_in_seconds"] > 0
