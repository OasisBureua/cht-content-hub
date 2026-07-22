"""Tests for admin clip-tag override API (SCRUM-75)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from jobs.playlist_doctor_tagger_core import tag_clips_from_playlists
from models.clip import Clip
from models.post import Post
from models.shoot import Shoot
from conftest import api_headers


@pytest.fixture
async def seeded_clip(db_session: AsyncSession) -> Clip:
    clip = Clip(
        id="clip-x",
        title="Test clip",
        tags=["drug:t-dxd", "biomarker:her2-low"],
    )
    db_session.add(clip)
    await db_session.flush()
    return clip


@pytest.mark.asyncio
async def test_get_requires_api_key(client: AsyncClient, seeded_clip):
    r = await client.get(f"/api/admin/clips/{seeded_clip.id}/tags")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_returns_tags_and_lock(client: AsyncClient, seeded_clip):
    r = await client.get(
        f"/api/admin/clips/{seeded_clip.id}/tags", headers=api_headers()
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == seeded_clip.id
    assert body["tags"] == ["drug:t-dxd", "biomarker:her2-low"]
    assert body["tags_curator_override"] is False


@pytest.mark.asyncio
async def test_get_404_missing(client: AsyncClient):
    r = await client.get("/api/admin/clips/nope/tags", headers=api_headers())
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_patch_tags_auto_locks(client: AsyncClient, seeded_clip):
    """Any tag write flips tags_curator_override to True implicitly."""
    r = await client.patch(
        f"/api/admin/clips/{seeded_clip.id}/tags",
        headers=api_headers(),
        json={"tags": ["drug:Enhertu", "doctor:Traina"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tags"] == ["drug:t-dxd", "doctor:Traina"]
    assert body["tags_curator_override"] is True


@pytest.mark.asyncio
async def test_patch_422_when_tags_reject(client: AsyncClient, seeded_clip):
    r = await client.patch(
        f"/api/admin/clips/{seeded_clip.id}/tags",
        headers=api_headers(),
        json={"tags": ["brand:enhertu"]},
    )
    assert r.status_code == 422
    body = r.json()
    assert body["statusCode"] == 422
    assert len(body["rejected"]) == 1
    assert "unknown namespace" in body["rejected"][0]["reason"]


@pytest.mark.asyncio
async def test_patch_can_clear_lock(client: AsyncClient, db_session: AsyncSession):
    """Explicitly re-open a locked clip to the tagger."""
    clip = Clip(id="clip-locked", title="locked", tags=["drug:t-dxd"], tags_curator_override=True)
    db_session.add(clip)
    await db_session.flush()

    r = await client.patch(
        "/api/admin/clips/clip-locked/tags",
        headers=api_headers(),
        json={"tags_curator_override": False},
    )
    assert r.status_code == 200
    assert r.json()["tags_curator_override"] is False


@pytest.mark.asyncio
async def test_patch_404_missing(client: AsyncClient):
    r = await client.patch(
        "/api/admin/clips/nope/tags",
        headers=api_headers(),
        json={"tags": ["drug:t-dxd"]},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_tagger_respects_curator_lock(
    db_session: AsyncSession, monkeypatch
):
    """Locked clip + post skip the daily tagger's rewrite; unlocked ones update."""
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    shoot = Shoot(
        id="shoot-lock",
        name="Traina lock test",
        youtube_playlist_id="PL_lock",
        doctors=[],
    )
    locked_clip = Clip(
        id="clip-locked-1",
        title="Locked",
        shoot_id="shoot-lock",
        tags=["drug:t-dxd", "doctor:CuratorPick"],
        tags_curator_override=True,
    )
    open_clip = Clip(
        id="clip-open-1",
        title="Open",
        shoot_id="shoot-lock",
        tags=["drug:t-dxd"],
        tags_curator_override=False,
    )
    locked_post = Post(
        id="post-locked-1",
        clip_id="clip-locked-1",
        shoot_id="shoot-lock",
        platform="youtube",
        channel="chm-official",
        provider_post_id="vid_l",
        tags=["drug:t-dxd", "doctor:CuratorPick"],
        tags_curator_override=True,
    )
    open_post = Post(
        id="post-open-1",
        clip_id="clip-open-1",
        shoot_id="shoot-lock",
        platform="youtube",
        channel="chm-official",
        provider_post_id="vid_o",
        tags=["drug:t-dxd"],
        tags_curator_override=False,
    )
    db_session.add_all([shoot, locked_clip, open_clip, locked_post, open_post])
    await db_session.flush()

    with (
        patch(
            "jobs.playlist_doctor_tagger_core.fetch_playlist_title",
            new=AsyncMock(return_value="Dr. Traina"),
        ),
        patch(
            "jobs.playlist_doctor_tagger_core.fetch_playlist_video_ids",
            new=AsyncMock(return_value=["vid_l", "vid_o"]),
        ),
    ):
        stats, _ = await tag_clips_from_playlists(db_session)

    assert stats.clips_curator_locked_skipped == 1
    assert stats.posts_curator_locked_skipped == 1
    assert stats.clips_changed == 1
    assert stats.posts_changed == 1

    await db_session.refresh(locked_clip)
    await db_session.refresh(open_clip)
    assert "doctor:CuratorPick" in locked_clip.tags
    assert "doctor:Traina" not in locked_clip.tags
    assert "doctor:Traina" in open_clip.tags
