"""End-to-end tagger test (SCRUM-72).

Exercises steps 4–6 of playlist_doctor_tagger against real Shoot + Clip +
Post rows in the test DB. YouTube API calls are mocked; everything else
runs against the live SQLite schema built by conftest.

Verifies:
  1. Clip/Post models ARE registered on the producer (guard flips ON).
  2. Shoot.doctors[] gets corrected from the parsed playlist title.
  3. Clip.tags gets the canonical doctor tags applied.
  4. Post.tags on chm-official gets the canonical doctor tags applied.
  5. Non-doctor tags (drug:, biomarker:) survive the rewrite untouched.
  6. Idempotent — second run produces zero further changes.
"""

from __future__ import annotations

from unittest.mock import patch, AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from jobs.playlist_doctor_tagger_core import (
    _load_clip_post_models,
    tag_clips_from_playlists,
)
from models.clip import Clip
from models.post import Post
from models.shoot import Shoot


def test_clip_post_models_loaded_on_producer():
    """SCRUM-72 activation gate: Clip + Post must import cleanly.

    Once this holds true, the tagger's `clip_post_active` flag flips ON and
    steps 4–6 execute instead of being skipped.
    """
    ClipCls, PostCls = _load_clip_post_models()
    assert ClipCls is Clip
    assert PostCls is Post


@pytest.fixture
async def seeded_shoot(db_session: AsyncSession) -> Shoot:
    """One shoot with a playlist, one clip on it, one chm-official post
    linked to that clip. Pre-existing non-doctor tags on clip + post that
    must survive the tagger's rewrite.
    """
    shoot = Shoot(
        id="shoot-1",
        name="Traina + Pegram — HER2 discussion",
        youtube_playlist_id="PL_test_playlist_1",
        doctors=["Dr. WrongName"],
    )
    clip = Clip(
        id="clip-1",
        title="Traina + Pegram clip",
        shoot_id="shoot-1",
        tags=["drug:T-DXd", "biomarker:HER2-low", "doctor:WrongName"],
    )
    post = Post(
        id="post-1",
        clip_id="clip-1",
        shoot_id="shoot-1",
        platform="youtube",
        channel="chm-official",
        provider_post_id="vid_A",
        tags=["drug:T-DXd", "doctor:WrongName"],
    )
    db_session.add_all([shoot, clip, post])
    await db_session.flush()
    return shoot


@pytest.mark.asyncio
async def test_tagger_propagates_to_clip_and_post(
    db_session: AsyncSession, seeded_shoot: Shoot, monkeypatch
):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    playlist_title = "Drs. Traina & Pegram | HER2 discussion"
    video_ids = ["vid_A"]

    with (
        patch(
            "jobs.playlist_doctor_tagger_core.fetch_playlist_title",
            new=AsyncMock(return_value=playlist_title),
        ),
        patch(
            "jobs.playlist_doctor_tagger_core.fetch_playlist_video_ids",
            new=AsyncMock(return_value=video_ids),
        ),
    ):
        stats, diffs = await tag_clips_from_playlists(db_session)

    assert stats.clip_post_skipped_models_missing is False, (
        "Clip/Post models must be active — the guard should not skip step 4-6"
    )
    assert stats.shoots_processed == 1
    assert stats.shoots_doctors_corrected == 1
    assert stats.clips_touched == 1
    assert stats.clips_changed == 1
    assert stats.posts_touched == 1
    assert stats.posts_changed == 1

    await db_session.refresh(seeded_shoot)
    assert set(seeded_shoot.doctors) == {"Dr. Traina", "Dr. Pegram"}

    clip = await db_session.get(Clip, "clip-1")
    assert clip is not None
    doctor_tags = sorted(t for t in clip.tags if t.startswith("doctor:"))
    assert doctor_tags == ["doctor:Pegram", "doctor:Traina"]
    # Taxonomy preserves freeform casing for non-alias'd values.
    assert "drug:T-DXd" in clip.tags
    assert "biomarker:HER2-low" in clip.tags
    assert "doctor:Wrongname" not in clip.tags
    assert "doctor:WrongName" not in clip.tags

    post = await db_session.get(Post, "post-1")
    assert post is not None
    post_doctor_tags = sorted(t for t in post.tags if t.startswith("doctor:"))
    assert post_doctor_tags == ["doctor:Pegram", "doctor:Traina"]
    assert "drug:T-DXd" in post.tags
    assert "doctor:Wrongname" not in post.tags

    entity_types = {d.entity_type for d in diffs}
    assert entity_types == {"shoot", "clip", "post"}


@pytest.mark.asyncio
async def test_tagger_is_idempotent(
    db_session: AsyncSession, seeded_shoot: Shoot, monkeypatch
):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    with (
        patch(
            "jobs.playlist_doctor_tagger_core.fetch_playlist_title",
            new=AsyncMock(return_value="Drs. Traina & Pegram"),
        ),
        patch(
            "jobs.playlist_doctor_tagger_core.fetch_playlist_video_ids",
            new=AsyncMock(return_value=["vid_A"]),
        ),
    ):
        await tag_clips_from_playlists(db_session)
        stats2, diffs2 = await tag_clips_from_playlists(db_session)

    assert stats2.shoots_doctors_corrected == 0
    assert stats2.clips_changed == 0
    assert stats2.posts_changed == 0
    assert diffs2 == []


@pytest.mark.asyncio
async def test_tagger_skips_posts_off_chm_official(
    db_session: AsyncSession, monkeypatch
):
    """Only chm-official posts get the doctor-tag rewrite. Posts on other
    channels (e.g. syndicated LinkedIn/X clones) are left alone.
    """
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    shoot = Shoot(
        id="shoot-2",
        name="Solo shoot",
        youtube_playlist_id="PL_solo",
        doctors=[],
    )
    clip = Clip(id="clip-2", title="Solo clip", shoot_id="shoot-2", tags=[])
    off_channel_post = Post(
        id="post-off",
        clip_id="clip-2",
        shoot_id="shoot-2",
        platform="linkedin",
        channel="chm-linkedin-syndicated",
        provider_post_id="vid_solo",
        tags=["drug:HR"],
    )
    db_session.add_all([shoot, clip, off_channel_post])
    await db_session.flush()

    with (
        patch(
            "jobs.playlist_doctor_tagger_core.fetch_playlist_title",
            new=AsyncMock(return_value="Dr. Traina | HR discussion"),
        ),
        patch(
            "jobs.playlist_doctor_tagger_core.fetch_playlist_video_ids",
            new=AsyncMock(return_value=["vid_solo"]),
        ),
    ):
        stats, _ = await tag_clips_from_playlists(db_session)

    assert stats.clips_changed == 1
    assert stats.posts_changed == 0

    await db_session.refresh(off_channel_post)
    assert off_channel_post.tags == ["drug:HR"]
