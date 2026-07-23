"""Tests for admin playlist-tag API (SCRUM-74)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from models.playlist_tag import PlaylistTag
from conftest import api_headers


@pytest.fixture
async def seeded_playlist_tag(db_session: AsyncSession) -> PlaylistTag:
    row = PlaylistTag(
        youtube_playlist_id="PL_test_curated",
        tags=["biomarker:her2-low", "drug:t-dxd"],
        lane="biomarker",
    )
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.mark.asyncio
async def test_get_requires_api_key(client: AsyncClient, seeded_playlist_tag):
    r = await client.get("/api/admin/playlists/PL_test_curated/tags")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_returns_row(client: AsyncClient, seeded_playlist_tag):
    r = await client.get(
        "/api/admin/playlists/PL_test_curated/tags", headers=api_headers()
    )
    assert r.status_code == 200
    body = r.json()
    assert body["youtube_playlist_id"] == "PL_test_curated"
    assert body["tags"] == ["biomarker:her2-low", "drug:t-dxd"]
    assert body["lane"] == "biomarker"


@pytest.mark.asyncio
async def test_get_404_when_missing(client: AsyncClient):
    r = await client.get(
        "/api/admin/playlists/does-not-exist/tags", headers=api_headers()
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_patch_updates_tags_via_taxonomy_normalization(
    client: AsyncClient, seeded_playlist_tag
):
    """Curator sends alias/typo variants; taxonomy collapses them to canonical.

    NOTE (2026-07-21): taxonomy revised to freeform values, so the outputs
    reflect the alias-corrected canonical spellings, not kebab-case:
      - drug:Enhertu → drug:t-dxd (alias in DRUG_CORRECTIONS)
      - biomarker:HER2LOW → biomarker:HER2-low (alias)
      - conference:ASCO2026 → conference:ASCO 2026 (alias)
    """
    r = await client.patch(
        "/api/admin/playlists/PL_test_curated/tags",
        headers=api_headers(),
        json={"tags": ["drug:Enhertu", "biomarker:HER2LOW", "conference:ASCO2026"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tags"] == [
        "drug:t-dxd",
        "biomarker:HER2-low",
        "conference:ASCO 2026",
    ]


@pytest.mark.asyncio
async def test_patch_lane_updates(client: AsyncClient, seeded_playlist_tag):
    r = await client.patch(
        "/api/admin/playlists/PL_test_curated/tags",
        headers=api_headers(),
        json={"lane": "drug"},
    )
    assert r.status_code == 200
    assert r.json()["lane"] == "drug"


@pytest.mark.asyncio
async def test_patch_lane_null_clears(client: AsyncClient, seeded_playlist_tag):
    r = await client.patch(
        "/api/admin/playlists/PL_test_curated/tags",
        headers=api_headers(),
        json={"lane": None},
    )
    assert r.status_code == 200
    assert r.json()["lane"] is None


@pytest.mark.asyncio
async def test_patch_invalid_lane_rejected(
    client: AsyncClient, seeded_playlist_tag
):
    r = await client.patch(
        "/api/admin/playlists/PL_test_curated/tags",
        headers=api_headers(),
        json={"lane": "nonsense"},
    )
    assert r.status_code == 422
    assert "nonsense" in r.text.lower() or "invalid lane" in r.text.lower()


@pytest.mark.asyncio
async def test_patch_422_when_tags_reject(client: AsyncClient, seeded_playlist_tag):
    r = await client.patch(
        "/api/admin/playlists/PL_test_curated/tags",
        headers=api_headers(),
        json={"tags": ["brand:enhertu", "not-a-tag"]},
    )
    assert r.status_code == 422
    body = r.json()
    assert body["statusCode"] == 422
    assert len(body["rejected"]) == 2
    reasons = {r["reason"] for r in body["rejected"]}
    assert any("unknown namespace" in r for r in reasons)
    assert any("not namespaced" in r for r in reasons)


@pytest.mark.asyncio
async def test_patch_empty_body_is_noop(client: AsyncClient, seeded_playlist_tag):
    r = await client.patch(
        "/api/admin/playlists/PL_test_curated/tags",
        headers=api_headers(),
        json={},
    )
    assert r.status_code == 200
    assert r.json()["tags"] == ["biomarker:her2-low", "drug:t-dxd"]


@pytest.mark.asyncio
async def test_patch_dedupes_via_taxonomy(client: AsyncClient, seeded_playlist_tag):
    r = await client.patch(
        "/api/admin/playlists/PL_test_curated/tags",
        headers=api_headers(),
        json={"tags": ["drug:Enhertu", "drug:t-dxd", "drug:trastuzumab-deruxtecan"]},
    )
    assert r.status_code == 200
    assert r.json()["tags"] == ["drug:t-dxd"]


@pytest.mark.asyncio
async def test_patch_upserts_when_missing(client: AsyncClient):
    """SCRUM-71 CH-8: PATCH auto-creates the row so population workflows
    (mapping WordPress editorial → YouTube playlists) can use the same
    endpoint without a separate CREATE route."""
    r = await client.patch(
        "/api/admin/playlists/PL_upsert_new/tags",
        headers=api_headers(),
        json={
            "tags": ["biomarker:HER2+", "drug:T-DXd"],
            "lane": "biomarker",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["youtube_playlist_id"] == "PL_upsert_new"
    assert body["tags"] == ["biomarker:HER2+", "drug:T-DXd"]
    assert body["lane"] == "biomarker"

    # Follow-up GET returns the created row.
    g = await client.get(
        "/api/admin/playlists/PL_upsert_new/tags", headers=api_headers()
    )
    assert g.status_code == 200
    assert g.json()["tags"] == ["biomarker:HER2+", "drug:T-DXd"]


@pytest.mark.asyncio
async def test_patch_upsert_creates_with_tags_only(client: AsyncClient):
    r = await client.patch(
        "/api/admin/playlists/PL_upsert_tags_only/tags",
        headers=api_headers(),
        json={"tags": ["biomarker:HR+"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tags"] == ["biomarker:HR+"]
    assert body["lane"] is None


@pytest.mark.asyncio
async def test_patch_upsert_creates_with_lane_only(client: AsyncClient):
    r = await client.patch(
        "/api/admin/playlists/PL_upsert_lane_only/tags",
        headers=api_headers(),
        json={"lane": "trial"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tags"] == []
    assert body["lane"] == "trial"


@pytest.mark.asyncio
async def test_patch_empty_body_against_missing_is_noop(client: AsyncClient):
    """Empty PATCH body on a missing row does not persist a phantom empty
    overlay — returns the default overlay shape without a DB write."""
    r = await client.patch(
        "/api/admin/playlists/PL_never_seen/tags",
        headers=api_headers(),
        json={},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["youtube_playlist_id"] == "PL_never_seen"
    assert body["tags"] == []
    assert body["lane"] is None

    # And no row was created.
    g = await client.get(
        "/api/admin/playlists/PL_never_seen/tags", headers=api_headers()
    )
    assert g.status_code == 404


@pytest.mark.asyncio
async def test_patch_upsert_rejects_invalid_tags_before_insert(client: AsyncClient):
    """Taxonomy validation runs before the insert decision — same 422
    semantics on create as on update."""
    r = await client.patch(
        "/api/admin/playlists/PL_upsert_reject/tags",
        headers=api_headers(),
        json={"tags": ["not-a-namespace-tag"]},
    )
    assert r.status_code == 422
    body = r.json()
    assert body["error"] == "Unprocessable Entity"
    assert body["rejected"]
    # And no row was created.
    g = await client.get(
        "/api/admin/playlists/PL_upsert_reject/tags", headers=api_headers()
    )
    assert g.status_code == 404


@pytest.mark.asyncio
async def test_patch_upsert_rejects_invalid_lane_before_insert(client: AsyncClient):
    r = await client.patch(
        "/api/admin/playlists/PL_upsert_bad_lane/tags",
        headers=api_headers(),
        json={"lane": "nonsense"},
    )
    assert r.status_code == 422
    # And no row was created.
    g = await client.get(
        "/api/admin/playlists/PL_upsert_bad_lane/tags", headers=api_headers()
    )
    assert g.status_code == 404
