"""Tests for SCRUM-77 tag filter semantics.

AND across namespaces, OR within a namespace. Verified at three layers:
  1. The pure helpers in services.tag_query.
  2. The /api/public/clips?tag= endpoint.
  3. The /api/public/playlists?tag= endpoint.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from models.clip import Clip
from models.playlist_tag import PlaylistTag
from services.tag_query import (
    group_tags_by_namespace,
    python_row_matches,
)
from conftest import api_headers


# ─── group_tags_by_namespace ───────────────────────────────────────────────


def test_group_single_namespace():
    assert group_tags_by_namespace(["drug:t-dxd"]) == {"drug": ["drug:t-dxd"]}


def test_group_two_namespaces():
    grouped = group_tags_by_namespace(["biomarker:her2-low", "drug:t-dxd"])
    assert grouped == {
        "biomarker": ["biomarker:her2-low"],
        "drug": ["drug:t-dxd"],
    }


def test_group_multiple_values_per_namespace_preserves_order():
    grouped = group_tags_by_namespace(
        ["biomarker:her2-low", "biomarker:her2-ultra-low", "drug:t-dxd"]
    )
    assert grouped == {
        "biomarker": ["biomarker:her2-low", "biomarker:her2-ultra-low"],
        "drug": ["drug:t-dxd"],
    }


def test_group_malformed_tag_treated_as_own_namespace():
    """No `:` in the tag ⇒ the whole string is the namespace. Effectively
    means the tag becomes an isolated group that has to match verbatim.
    """
    grouped = group_tags_by_namespace(["notnamespaced", "drug:t-dxd"])
    assert grouped == {
        "notnamespaced": ["notnamespaced"],
        "drug": ["drug:t-dxd"],
    }


# ─── python_row_matches ────────────────────────────────────────────────────


def test_empty_tags_list_matches_anything():
    assert python_row_matches(["drug:t-dxd"], []) is True
    assert python_row_matches([], []) is True
    assert python_row_matches(None, []) is True


def test_single_namespace_match():
    assert python_row_matches(["drug:t-dxd", "biomarker:her2-low"], ["drug:t-dxd"]) is True
    assert python_row_matches(["biomarker:her2-low"], ["drug:t-dxd"]) is False


def test_and_across_namespaces():
    """Row must satisfy every namespace in the query."""
    row = ["biomarker:her2-low", "drug:t-dxd"]
    assert python_row_matches(row, ["biomarker:her2-low", "drug:t-dxd"]) is True

    row_missing_drug = ["biomarker:her2-low"]
    assert (
        python_row_matches(row_missing_drug, ["biomarker:her2-low", "drug:t-dxd"])
        is False
    )


def test_or_within_namespace():
    """Row need only match ONE of the tags within a namespace."""
    tags_list = ["biomarker:her2-low", "biomarker:her2-ultra-low"]
    assert python_row_matches(["biomarker:her2-low"], tags_list) is True
    assert python_row_matches(["biomarker:her2-ultra-low"], tags_list) is True
    assert python_row_matches(["biomarker:triple-negative"], tags_list) is False


def test_mixed_and_across_or_within():
    """Ticket example: (biomarker in {her2-low OR her2-ultra-low}) AND drug=t-dxd."""
    tags_list = [
        "biomarker:her2-low",
        "biomarker:her2-ultra-low",
        "drug:t-dxd",
    ]
    assert python_row_matches(
        ["biomarker:her2-low", "drug:t-dxd"], tags_list
    ) is True
    assert python_row_matches(
        ["biomarker:her2-ultra-low", "drug:t-dxd"], tags_list
    ) is True
    # Missing drug — fails
    assert python_row_matches(["biomarker:her2-low"], tags_list) is False
    # Missing both biomarker values — fails
    assert python_row_matches(["drug:t-dxd"], tags_list) is False


# ─── /api/public/clips?tag= end-to-end ─────────────────────────────────────


@pytest.fixture
async def seeded_clips(db_session: AsyncSession):
    clips = [
        Clip(
            id="official:youtube:her2low-tdxd",
            title="her2-low + t-dxd",
            channel="chm-official",
            tags=["biomarker:her2-low", "drug:t-dxd"],
        ),
        Clip(
            id="official:youtube:her2ul-tdxd",
            title="her2-ultra-low + t-dxd",
            channel="chm-official",
            tags=["biomarker:her2-ultra-low", "drug:t-dxd"],
        ),
        Clip(
            id="official:youtube:her2low-sg",
            title="her2-low + sg",
            channel="chm-official",
            tags=["biomarker:her2-low", "drug:sg"],
        ),
        Clip(
            id="official:youtube:tnbc",
            title="triple negative only",
            channel="chm-official",
            tags=["biomarker:triple-negative"],
        ),
    ]
    db_session.add_all(clips)
    await db_session.flush()
    return clips


@pytest.mark.asyncio
async def test_clips_and_across_namespaces(client: AsyncClient, seeded_clips):
    r = await client.get(
        "/api/public/clips?tag=biomarker:her2-low,drug:t-dxd",
        headers=api_headers(),
    )
    assert r.status_code == 200
    titles = {c["title"] for c in r.json()}
    assert titles == {"her2-low + t-dxd"}


@pytest.mark.asyncio
async def test_clips_or_within_namespace(client: AsyncClient, seeded_clips):
    r = await client.get(
        "/api/public/clips?tag=biomarker:her2-low,biomarker:her2-ultra-low,drug:t-dxd",
        headers=api_headers(),
    )
    assert r.status_code == 200
    titles = {c["title"] for c in r.json()}
    assert titles == {"her2-low + t-dxd", "her2-ultra-low + t-dxd"}


@pytest.mark.asyncio
async def test_clips_single_tag_still_works(client: AsyncClient, seeded_clips):
    r = await client.get(
        "/api/public/clips?tag=drug:t-dxd", headers=api_headers()
    )
    titles = {c["title"] for c in r.json()}
    assert titles == {"her2-low + t-dxd", "her2-ultra-low + t-dxd"}


# ─── /api/public/playlists?tag= end-to-end ─────────────────────────────────


@pytest.fixture
async def seeded_playlists(db_session: AsyncSession):
    playlists = [
        PlaylistTag(
            youtube_playlist_id="PL_her2low",
            tags=["biomarker:her2-low", "drug:t-dxd"],
            lane="biomarker",
        ),
        PlaylistTag(
            youtube_playlist_id="PL_her2ul",
            tags=["biomarker:her2-ultra-low", "drug:t-dxd"],
            lane="biomarker",
        ),
        PlaylistTag(
            youtube_playlist_id="PL_tnbc",
            tags=["biomarker:triple-negative"],
            lane="biomarker",
        ),
    ]
    db_session.add_all(playlists)
    await db_session.flush()
    return playlists


@pytest.mark.asyncio
async def test_playlists_or_within_namespace(client: AsyncClient, seeded_playlists):
    r = await client.get(
        "/api/public/playlists?tag=biomarker:her2-low,biomarker:her2-ultra-low",
        headers=api_headers(),
    )
    assert r.status_code == 200
    ids = {p["youtube_playlist_id"] for p in r.json()["items"]}
    assert ids == {"PL_her2low", "PL_her2ul"}


@pytest.mark.asyncio
async def test_playlists_and_across_namespaces(
    client: AsyncClient, seeded_playlists
):
    r = await client.get(
        "/api/public/playlists?tag=biomarker:her2-low,drug:t-dxd",
        headers=api_headers(),
    )
    ids = {p["youtube_playlist_id"] for p in r.json()["items"]}
    assert ids == {"PL_her2low"}
