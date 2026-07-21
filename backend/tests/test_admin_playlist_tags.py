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
    """Curator sends mixed-case brand names; taxonomy normalizes them."""
    r = await client.patch(
        "/api/admin/playlists/PL_test_curated/tags",
        headers=api_headers(),
        json={"tags": ["drug:Enhertu", "biomarker:HER2LOW", "conference:ASCO2026"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tags"] == [
        "drug:t-dxd",
        "biomarker:her2-low",
        "conference:asco-2026",
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
async def test_patch_404_when_missing(client: AsyncClient):
    r = await client.patch(
        "/api/admin/playlists/nope/tags",
        headers=api_headers(),
        json={"lane": "biomarker"},
    )
    assert r.status_code == 404
