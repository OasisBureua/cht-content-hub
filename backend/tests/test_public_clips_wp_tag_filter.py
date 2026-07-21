"""Piece 1b: /api/public/clips?tag= with WP-projected namespaces.

Verifies that:
  - ?tag=topic:her2 returns clips whose linked WP post has 'her2' in categories
  - ?tag=wp:some-tag returns clips whose linked WP post has 'some-tag' in tags
  - Mixing WP-projected with Clip.tags namespaces AND-across them
  - Multiple values within topic: (topic:her2,topic:hr) OR-within
  - Deleted WP events don't contribute
  - Clips without a matching WP post are excluded when a WP filter is active
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import api_headers
from models.clip import Clip


async def _insert_wp(
    db: AsyncSession,
    *,
    post_id: int,
    slug: str,
    categories: list[str] | None = None,
    tags: list[str] | None = None,
    youtube_video_id: str | None = None,
    event: str = "published",
    modified_gmt: datetime | None = None,
) -> None:
    modified_gmt = modified_gmt or datetime.now(timezone.utc)
    await db.execute(
        text(
            """
            INSERT INTO wordpress_events (
                post_id, modified_gmt, event, post_type, slug, title, status,
                permalink, categories, tags, site_url, acf, raw_payload,
                signature_verified, received_at, youtube_video_id, featured_media_url
            ) VALUES (
                :post_id, :modified_gmt, :event, 'post', :slug, 'title', 'publish',
                :permalink, :categories, :tags, 'https://communityhealth.media',
                NULL, :raw_payload, 1, :received_at, :yt, NULL
            )
            """
        ),
        {
            "post_id": post_id,
            "modified_gmt": modified_gmt,
            "event": event,
            "slug": slug,
            "permalink": f"https://communityhealth.media/{slug}/",
            "categories": json.dumps(categories or []),
            "tags": json.dumps(tags or []),
            "raw_payload": json.dumps({}),
            "received_at": modified_gmt,
            "yt": youtube_video_id,
        },
    )


@pytest.fixture
async def seeded_wp_clips(db_session: AsyncSession):
    await _insert_wp(
        db_session,
        post_id=1,
        slug="her2-post",
        categories=["her2", "mbc"],
        tags=["adc-therapy"],
        youtube_video_id="vid_her2",
    )
    await _insert_wp(
        db_session,
        post_id=2,
        slug="hr-post",
        categories=["hr", "mbc"],
        tags=["cdk46"],
        youtube_video_id="vid_hr",
    )
    await _insert_wp(
        db_session,
        post_id=3,
        slug="tnbc-post",
        categories=["triple-negative"],
        tags=[],
        youtube_video_id="vid_tnbc",
    )
    await _insert_wp(
        db_session,
        post_id=99,
        slug="deleted",
        event="deleted",
        categories=["her2"],
        tags=["adc-therapy"],
        youtube_video_id="vid_deleted",
    )

    for vid, extra_tags in (
        ("vid_her2", ["biomarker:HER2+", "drug:T-DXd", "doctor:Traina"]),
        ("vid_hr", ["biomarker:HR+", "drug:Kisqali", "doctor:Pegram"]),
        ("vid_tnbc", ["biomarker:triple-negative", "doctor:Iyengar"]),
        ("vid_orphan", ["biomarker:HER2+"]),
        ("vid_deleted", ["biomarker:HER2+"]),
    ):
        db_session.add(
            Clip(
                id=f"official:youtube:{vid}",
                title=f"Clip {vid}",
                channel="chm-official",
                platform="youtube",
                tags=extra_tags,
            )
        )
    await db_session.flush()


@pytest.mark.asyncio
async def test_filter_topic_matches_wp_categories(client: AsyncClient, seeded_wp_clips):
    r = await client.get(
        "/api/public/clips?tag=topic:her2&platform=youtube",
        headers=api_headers(),
    )
    assert r.status_code == 200
    ids = {c["id"] for c in r.json()}
    assert ids == {"official:youtube:vid_her2"}


@pytest.mark.asyncio
async def test_filter_wp_tag_matches_wp_tags(client: AsyncClient, seeded_wp_clips):
    r = await client.get(
        "/api/public/clips?tag=wp:cdk46&platform=youtube",
        headers=api_headers(),
    )
    ids = {c["id"] for c in r.json()}
    assert ids == {"official:youtube:vid_hr"}


@pytest.mark.asyncio
async def test_filter_multiple_topics_or_within(client: AsyncClient, seeded_wp_clips):
    r = await client.get(
        "/api/public/clips?tag=topic:her2,topic:hr&platform=youtube",
        headers=api_headers(),
    )
    ids = {c["id"] for c in r.json()}
    assert ids == {"official:youtube:vid_her2", "official:youtube:vid_hr"}


@pytest.mark.asyncio
async def test_filter_topic_and_clip_side_tags_intersect(
    client: AsyncClient, seeded_wp_clips
):
    """topic:her2 (WP) AND drug:T-DXd (Clip.tags) — both must match."""
    r = await client.get(
        "/api/public/clips?tag=topic:her2,drug:T-DXd&platform=youtube",
        headers=api_headers(),
    )
    ids = {c["id"] for c in r.json()}
    assert ids == {"official:youtube:vid_her2"}


@pytest.mark.asyncio
async def test_filter_deleted_wp_events_excluded(client: AsyncClient, seeded_wp_clips):
    r = await client.get(
        "/api/public/clips?tag=topic:her2&platform=youtube",
        headers=api_headers(),
    )
    ids = {c["id"] for c in r.json()}
    assert "official:youtube:vid_deleted" not in ids


@pytest.mark.asyncio
async def test_filter_orphan_clip_excluded_when_wp_filter_active(
    client: AsyncClient, seeded_wp_clips
):
    r = await client.get(
        "/api/public/clips?tag=topic:her2&platform=youtube",
        headers=api_headers(),
    )
    ids = {c["id"] for c in r.json()}
    assert "official:youtube:vid_orphan" not in ids


@pytest.mark.asyncio
async def test_filter_clip_side_only_does_not_require_wp(
    client: AsyncClient, seeded_wp_clips
):
    """biomarker:HER2+ alone matches on Clip.tags, no WP join required."""
    r = await client.get(
        "/api/public/clips?tag=biomarker:HER2%2B&platform=youtube",
        headers=api_headers(),
    )
    ids = {c["id"] for c in r.json()}
    assert "official:youtube:vid_orphan" in ids


@pytest.mark.asyncio
async def test_filter_wp_tag_and_topic_intersect(client: AsyncClient, seeded_wp_clips):
    r = await client.get(
        "/api/public/clips?tag=topic:her2,wp:adc-therapy&platform=youtube",
        headers=api_headers(),
    )
    ids = {c["id"] for c in r.json()}
    assert ids == {"official:youtube:vid_her2"}
