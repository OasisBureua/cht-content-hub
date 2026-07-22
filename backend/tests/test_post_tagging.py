"""Tests for post_tagging (YouTube snippet.tags → Clip.tags, Piece 2).

Verifies:
  - Fresh yt:* tags applied from mocked snippet response
  - Freeform values pass through (spaces, mixed case, +)
  - Non-yt namespaces on Clip.tags untouched (biomarker/drug/doctor/etc.)
  - Curator-locked clips skipped
  - Deleted-from-YT clips retain existing yt:* (missing_from_yt counted)
  - Idempotent — second run is 0 changes
  - Empty snippet.tags = strip all yt:* (YouTube is source of truth)
  - Only chm-official + platform=youtube considered
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from jobs.post_tagging_core import (
    _clip_youtube_id,
    _strip_yt_tags,
    merge_yt_tags,
    tag_clips_from_youtube,
)
from models.clip import Clip


# ─── pure helpers ──────────────────────────────────────────────────────────


def test_strip_yt_tags():
    assert _strip_yt_tags(["yt:foo", "drug:t-dxd", "yt:bar"]) == ["drug:t-dxd"]
    assert _strip_yt_tags([]) == []
    assert _strip_yt_tags(None) == []


def test_merge_yt_tags_replaces_yt_slice():
    existing = ["yt:old-one", "drug:t-dxd", "doctor:Traina", "yt:old-two"]
    canonical = ["yt:new-alpha", "yt:new-beta"]
    result = merge_yt_tags(existing, canonical)
    assert result == [
        "drug:t-dxd",
        "doctor:Traina",
        "yt:new-alpha",
        "yt:new-beta",
    ]


def test_merge_yt_tags_idempotent_when_equal():
    existing = ["drug:t-dxd", "yt:foo", "yt:bar"]
    canonical = ["yt:foo", "yt:bar"]
    assert merge_yt_tags(existing, canonical) == existing


def test_merge_yt_tags_dedupes():
    existing = ["yt:foo", "drug:t-dxd"]
    canonical = ["yt:foo", "yt:foo", "yt:bar"]
    result = merge_yt_tags(existing, canonical)
    assert result == ["drug:t-dxd", "yt:foo", "yt:bar"]


def test_clip_youtube_id_extraction():
    class MockClip:
        def __init__(self, id_: str, platform: str = "youtube"):
            self.id = id_
            self.platform = platform

    assert _clip_youtube_id(MockClip("official:youtube:abc123")) == "abc123"
    assert _clip_youtube_id(MockClip("branded:youtube:xyz")) == "xyz"
    assert _clip_youtube_id(MockClip("official:youtube:", "youtube")) is None
    assert _clip_youtube_id(MockClip("official:linkedin:abc", "linkedin")) is None
    assert _clip_youtube_id(MockClip("malformed")) is None


# ─── e2e via mocked fetch ──────────────────────────────────────────────────


class _FakeFetch:
    def __init__(self, response: dict[str, list[str]]):
        self.response = response
        self.calls: list[list[str]] = []

    async def __call__(self, video_ids, api_key):
        self.calls.append(list(video_ids))
        return {
            vid: self.response.get(vid, [])
            for vid in video_ids
            if vid in self.response
        }


@pytest.fixture
async def seeded_clips(db_session: AsyncSession):
    clips = [
        Clip(
            id="official:youtube:vidA",
            title="A",
            channel="chm-official",
            platform="youtube",
            tags=["drug:t-dxd", "doctor:Traina", "yt:old-tag-a"],
        ),
        Clip(
            id="official:youtube:vidB",
            title="B",
            channel="chm-official",
            platform="youtube",
            tags=["biomarker:HER2+"],
        ),
        Clip(
            id="official:youtube:vidLocked",
            title="Locked",
            channel="chm-official",
            platform="youtube",
            tags=["yt:should-stay"],
            tags_curator_override=True,
        ),
        Clip(
            id="branded:youtube:vidX",
            title="Off-channel",
            channel="branded",
            platform="youtube",
            tags=["yt:untouched-off-channel"],
        ),
    ]
    db_session.add_all(clips)
    await db_session.flush()
    return {c.id: c for c in clips}


@pytest.mark.asyncio
async def test_applies_yt_tags_freeform_values(
    db_session: AsyncSession, seeded_clips, monkeypatch
):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    fake = _FakeFetch(
        {
            "vidA": ["HER2 Positive", "Breast Cancer", "TB01"],
            "vidB": ["adc therapy", "HER2-low"],
        }
    )
    stats = await tag_clips_from_youtube(db_session, fetch=fake)

    assert stats.clips_processed == 3
    assert stats.clips_with_yt_id == 3
    assert stats.clips_changed == 2
    # vidLocked is BOTH curator-locked AND absent from the fake YT response.
    # The lock check runs first, so it counts as locked, not missing.
    assert stats.clips_curator_locked_skipped == 1
    assert stats.clips_missing_from_yt == 0

    await db_session.refresh(seeded_clips["official:youtube:vidA"])
    a_tags = seeded_clips["official:youtube:vidA"].tags
    assert "drug:t-dxd" in a_tags
    assert "doctor:Traina" in a_tags
    assert "yt:HER2 Positive" in a_tags
    assert "yt:Breast Cancer" in a_tags
    assert "yt:TB01" in a_tags
    assert "yt:old-tag-a" not in a_tags

    await db_session.refresh(seeded_clips["official:youtube:vidB"])
    b_tags = seeded_clips["official:youtube:vidB"].tags
    assert "biomarker:HER2+" in b_tags
    assert "yt:adc therapy" in b_tags
    assert "yt:HER2-low" in b_tags


@pytest.mark.asyncio
async def test_curator_locked_skipped(
    db_session: AsyncSession, seeded_clips, monkeypatch
):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    fake = _FakeFetch({"vidLocked": ["would-overwrite"]})
    stats = await tag_clips_from_youtube(db_session, fetch=fake)

    assert stats.clips_curator_locked_skipped == 1
    await db_session.refresh(seeded_clips["official:youtube:vidLocked"])
    tags = seeded_clips["official:youtube:vidLocked"].tags
    assert "yt:should-stay" in tags
    assert "yt:would-overwrite" not in tags


@pytest.mark.asyncio
async def test_missing_from_youtube_preserves_existing_yt(
    db_session: AsyncSession, seeded_clips, monkeypatch
):
    """Clip whose YT video no longer exists — Lambda leaves existing yt:* alone.

    Rationale: video might be temporarily unlisted; don't strip its tags
    on a single missed fetch. A separate cleanup job would purge orphan clips
    if that's ever needed.
    """
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    fake = _FakeFetch({})
    stats = await tag_clips_from_youtube(db_session, fetch=fake)

    # vidLocked is caught by curator-lock first; only vidA + vidB register
    # as missing_from_yt.
    assert stats.clips_missing_from_yt == 2
    assert stats.clips_curator_locked_skipped == 1
    assert stats.clips_changed == 0
    await db_session.refresh(seeded_clips["official:youtube:vidA"])
    assert "yt:old-tag-a" in seeded_clips["official:youtube:vidA"].tags


@pytest.mark.asyncio
async def test_idempotent_second_run(
    db_session: AsyncSession, seeded_clips, monkeypatch
):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    fake = _FakeFetch({"vidA": ["stable-tag"], "vidB": ["stable-tag"]})

    stats1 = await tag_clips_from_youtube(db_session, fetch=fake)
    stats2 = await tag_clips_from_youtube(db_session, fetch=fake)

    assert stats1.clips_changed == 2
    assert stats2.clips_changed == 0


@pytest.mark.asyncio
async def test_empty_snippet_tags_strips_yt_slice(
    db_session: AsyncSession, seeded_clips, monkeypatch
):
    """YouTube is source of truth for yt:*; empty snippet.tags = drop all."""
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    fake = _FakeFetch({"vidA": []})
    stats = await tag_clips_from_youtube(db_session, fetch=fake)

    await db_session.refresh(seeded_clips["official:youtube:vidA"])
    a_tags = seeded_clips["official:youtube:vidA"].tags
    assert "yt:old-tag-a" not in a_tags
    assert "drug:t-dxd" in a_tags
    assert stats.clips_changed >= 1


@pytest.mark.asyncio
async def test_off_channel_and_non_youtube_clips_excluded(
    db_session: AsyncSession, seeded_clips, monkeypatch
):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    fake = _FakeFetch({"vidA": ["should-apply"], "vidX": ["should-not-apply"]})
    await tag_clips_from_youtube(db_session, fetch=fake)

    await db_session.refresh(seeded_clips["branded:youtube:vidX"])
    branded_tags = seeded_clips["branded:youtube:vidX"].tags
    assert "yt:untouched-off-channel" in branded_tags
    assert "yt:should-not-apply" not in branded_tags


@pytest.mark.asyncio
async def test_dry_run_no_writes(
    db_session: AsyncSession, seeded_clips, monkeypatch
):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    fake = _FakeFetch({"vidA": ["new-yt-tag"]})
    stats = await tag_clips_from_youtube(db_session, fetch=fake, dry_run=True)

    assert stats.clips_changed >= 1
    await db_session.refresh(seeded_clips["official:youtube:vidA"])
    a_tags = seeded_clips["official:youtube:vidA"].tags
    assert "yt:new-yt-tag" not in a_tags
    assert "yt:old-tag-a" in a_tags


@pytest.mark.asyncio
async def test_missing_api_key_raises(db_session, monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="YOUTUBE_API_KEY"):
        await tag_clips_from_youtube(db_session)
