"""Tests for tag_reconcile (SCRUM-76)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from jobs.tag_reconcile import reconcile_tags
from models.clip import Clip
from models.shoot import Shoot


def _make_404_error() -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example/playlists")
    response = httpx.Response(status_code=404, request=request)
    return httpx.HTTPStatusError("not found", request=request, response=response)


@pytest.fixture
async def seeded_env(db_session: AsyncSession):
    live_shoot = Shoot(
        id="shoot-live",
        name="Live shoot",
        youtube_playlist_id="PL_live",
        doctors=[],
    )
    dead_shoot = Shoot(
        id="shoot-dead",
        name="Dead shoot",
        youtube_playlist_id="PL_dead",
        doctors=[],
    )
    live_tagged = Clip(
        id="clip-tagged",
        title="Already tagged",
        channel="chm-official",
        shoot_id="shoot-live",
        tags=["drug:t-dxd", "doctor:Traina"],
    )
    untagged = Clip(
        id="clip-untagged",
        title="Missing doctor tag",
        channel="chm-official",
        shoot_id="shoot-live",
        tags=["drug:t-dxd"],
    )
    off_channel = Clip(
        id="clip-off",
        title="Off channel — not counted",
        channel="chm-linkedin",
        shoot_id="shoot-live",
        tags=[],
    )
    db_session.add_all([live_shoot, dead_shoot, live_tagged, untagged, off_channel])
    await db_session.flush()
    return {"live_shoot": live_shoot, "dead_shoot": dead_shoot}


@pytest.mark.asyncio
async def test_prunes_dead_playlist_and_reports(
    db_session: AsyncSession, seeded_env, monkeypatch
):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    async def title_side_effect(playlist_id, api_key, *, client=None):
        if playlist_id == "PL_dead":
            raise _make_404_error()
        return "Dr. Traina"

    with (
        patch(
            "jobs.playlist_doctor_tagger.fetch_playlist_title",
            new=AsyncMock(side_effect=title_side_effect),
        ),
        patch(
            "jobs.playlist_doctor_tagger.fetch_playlist_video_ids",
            new=AsyncMock(return_value=[]),
        ),
    ):
        report = await reconcile_tags(db_session)

    assert "PL_dead" in report.tagger_stats.playlists_orphaned_404
    assert report.pruned_shoot_ids == ["shoot-dead"]

    await db_session.refresh(seeded_env["dead_shoot"])
    assert seeded_env["dead_shoot"].youtube_playlist_id is None

    await db_session.refresh(seeded_env["live_shoot"])
    assert seeded_env["live_shoot"].youtube_playlist_id == "PL_live"


@pytest.mark.asyncio
async def test_reports_untagged_clips_on_chm_official(
    db_session: AsyncSession, seeded_env, monkeypatch
):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    with (
        patch(
            "jobs.playlist_doctor_tagger.fetch_playlist_title",
            new=AsyncMock(return_value="Dr. Traina"),
        ),
        patch(
            "jobs.playlist_doctor_tagger.fetch_playlist_video_ids",
            new=AsyncMock(return_value=[]),
        ),
    ):
        report = await reconcile_tags(db_session)

    assert "clip-untagged" in report.untagged_clip_ids
    assert "clip-tagged" not in report.untagged_clip_ids
    assert "clip-off" not in report.untagged_clip_ids


@pytest.mark.asyncio
async def test_dry_run_writes_nothing(
    db_session: AsyncSession, seeded_env, monkeypatch
):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    async def title_side_effect(playlist_id, api_key, *, client=None):
        if playlist_id == "PL_dead":
            raise _make_404_error()
        return "Dr. Traina"

    with (
        patch(
            "jobs.playlist_doctor_tagger.fetch_playlist_title",
            new=AsyncMock(side_effect=title_side_effect),
        ),
        patch(
            "jobs.playlist_doctor_tagger.fetch_playlist_video_ids",
            new=AsyncMock(return_value=[]),
        ),
    ):
        report = await reconcile_tags(db_session, dry_run=True)

    assert report.pruned_shoot_ids == ["shoot-dead"]

    await db_session.refresh(seeded_env["dead_shoot"])
    assert seeded_env["dead_shoot"].youtube_playlist_id == "PL_dead"


@pytest.mark.asyncio
async def test_prune_disabled_leaves_dead_shoots_intact(
    db_session: AsyncSession, seeded_env, monkeypatch
):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    async def title_side_effect(playlist_id, api_key, *, client=None):
        if playlist_id == "PL_dead":
            raise _make_404_error()
        return "Dr. Traina"

    with (
        patch(
            "jobs.playlist_doctor_tagger.fetch_playlist_title",
            new=AsyncMock(side_effect=title_side_effect),
        ),
        patch(
            "jobs.playlist_doctor_tagger.fetch_playlist_video_ids",
            new=AsyncMock(return_value=[]),
        ),
    ):
        report = await reconcile_tags(db_session, prune_dead_playlists=False)

    assert report.pruned_shoot_ids == []
    await db_session.refresh(seeded_env["dead_shoot"])
    assert seeded_env["dead_shoot"].youtube_playlist_id == "PL_dead"
