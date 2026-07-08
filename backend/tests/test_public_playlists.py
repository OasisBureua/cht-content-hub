"""Integration tests for /api/public/playlists endpoint.

Verifies auth, empty state, filters (tag, lane), pagination, and the
X-Total-Count header. Uses the same in-memory SQLite pattern as the
existing KOL endpoint tests.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import API_KEY, api_headers
from models.playlist_tag import PlaylistTag


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
async def seeded_playlists(db_session: AsyncSession):
    """Seed a small set of PlaylistTag rows covering multiple lanes and tags."""
    rows = [
        PlaylistTag(
            youtube_playlist_id="PL_biomarker_her2",
            tags=["biomarker:HER2+", "drug:T-DXd"],
            lane="biomarker",
        ),
        PlaylistTag(
            youtube_playlist_id="PL_biomarker_cns",
            tags=["biomarker:HER2+", "topic:CNS"],
            lane="biomarker",
        ),
        PlaylistTag(
            youtube_playlist_id="PL_drug_dato",
            tags=["drug:Datopotamab"],
            lane="drug",
        ),
        PlaylistTag(
            youtube_playlist_id="PL_trial_db09",
            tags=["trial:DESTINY-Breast09"],
            lane="trial",
        ),
        PlaylistTag(
            youtube_playlist_id="PL_archive_older",
            tags=["biomarker:HER2+"],
            lane="archive",
        ),
    ]
    db_session.add_all(rows)
    await db_session.commit()
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_playlists_requires_api_key(http_client: AsyncClient):
    response = await http_client.get("/api/public/playlists")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "AUTH_INVALID_KEY"


@pytest.mark.asyncio
async def test_playlists_rejects_invalid_api_key(http_client: AsyncClient):
    response = await http_client.get(
        "/api/public/playlists",
        headers={"X-API-Key": "wrong-key"},
    )
    assert response.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# Empty state
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_playlists_empty_list(client: AsyncClient):
    response = await client.get("/api/public/playlists", headers=api_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert response.headers.get("X-Total-Count") == "0"


# ─────────────────────────────────────────────────────────────────────────────
# List behavior
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_playlists_list_all(client: AsyncClient, seeded_playlists):
    response = await client.get("/api/public/playlists", headers=api_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert len(body["items"]) == 5
    assert response.headers["X-Total-Count"] == "5"
    # Response shape
    first = body["items"][0]
    assert "youtube_playlist_id" in first
    assert "tags" in first
    assert "lane" in first


# ─────────────────────────────────────────────────────────────────────────────
# Filters
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_playlists_filter_by_lane(client: AsyncClient, seeded_playlists):
    response = await client.get(
        "/api/public/playlists",
        headers=api_headers(),
        params={"lane": "biomarker"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert all(item["lane"] == "biomarker" for item in body["items"])


@pytest.mark.asyncio
async def test_playlists_filter_by_single_tag(client: AsyncClient, seeded_playlists):
    response = await client.get(
        "/api/public/playlists",
        headers=api_headers(),
        params={"tag": "biomarker:HER2+"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3  # both biomarker + archive
    ids = {item["youtube_playlist_id"] for item in body["items"]}
    assert ids == {"PL_biomarker_her2", "PL_biomarker_cns", "PL_archive_older"}


@pytest.mark.asyncio
async def test_playlists_filter_by_multiple_tags_and_logic(
    client: AsyncClient, seeded_playlists
):
    """?tag=A,B should return playlists containing BOTH A AND B."""
    response = await client.get(
        "/api/public/playlists",
        headers=api_headers(),
        params={"tag": "biomarker:HER2+,topic:CNS"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["youtube_playlist_id"] == "PL_biomarker_cns"


@pytest.mark.asyncio
async def test_playlists_filter_by_lane_and_tag(client: AsyncClient, seeded_playlists):
    response = await client.get(
        "/api/public/playlists",
        headers=api_headers(),
        params={"lane": "biomarker", "tag": "topic:CNS"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["youtube_playlist_id"] == "PL_biomarker_cns"


@pytest.mark.asyncio
async def test_playlists_invalid_lane_rejected(client: AsyncClient):
    """Lanes not in the enum should 422."""
    response = await client.get(
        "/api/public/playlists",
        headers=api_headers(),
        params={"lane": "not-a-real-lane"},
    )
    assert response.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# Pagination
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_playlists_pagination(client: AsyncClient, seeded_playlists):
    response = await client.get(
        "/api/public/playlists",
        headers=api_headers(),
        params={"limit": 2, "offset": 0},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert body["total"] == 5  # unpaginated total
    assert response.headers["X-Total-Count"] == "5"


@pytest.mark.asyncio
async def test_playlists_limit_upper_bound(client: AsyncClient):
    """limit above 200 is rejected."""
    response = await client.get(
        "/api/public/playlists",
        headers=api_headers(),
        params={"limit": 500},
    )
    assert response.status_code == 422
