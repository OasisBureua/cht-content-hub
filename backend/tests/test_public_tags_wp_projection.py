"""Tests for /api/public/tags WP projection (SCRUM-79 backend + Piece 1).

Verifies that the endpoint unions:
  - Clip.tags (namespaced or bare → "other")
  - Post.tags (same)
  - wordpress_events.categories → `topic:*`
  - wordpress_events.tags → `wp:*`

WordPress rows are seeded via raw SQL because JSONB doesn't round-trip
on SQLite via ORM. Same pattern as test_public_wordpress.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import api_headers
from models.clip import Clip


async def _insert_wp_event(
    db: AsyncSession,
    *,
    post_id: int,
    slug: str,
    title: str = "post",
    event: str = "published",
    modified_gmt: datetime | None = None,
    categories: list[str] | None = None,
    tags: list[str] | None = None,
    youtube_video_id: str | None = None,
) -> None:
    modified_gmt = modified_gmt or datetime.now(timezone.utc)
    await db.execute(
        text(
            """
            INSERT INTO wordpress_events (
                post_id, modified_gmt, event, post_type, slug, title, status,
                permalink, categories, tags, site_url, acf, raw_payload,
                signature_verified, received_at,
                youtube_video_id, featured_media_url
            ) VALUES (
                :post_id, :modified_gmt, :event, 'post', :slug, :title, 'publish',
                :permalink, :categories, :tags, 'https://communityhealth.media',
                NULL, :raw_payload, 1, :received_at,
                :youtube_video_id, NULL
            )
            """
        ),
        {
            "post_id": post_id,
            "modified_gmt": modified_gmt,
            "event": event,
            "slug": slug,
            "title": title,
            "permalink": f"https://communityhealth.media/{slug}/",
            "categories": json.dumps(categories or []),
            "tags": json.dumps(tags or []),
            "raw_payload": json.dumps({"post_id": post_id}),
            "received_at": modified_gmt,
            "youtube_video_id": youtube_video_id,
        },
    )


@pytest.fixture
async def seeded_wp_and_clips(db_session: AsyncSession):
    """WP events + a clip with existing namespaced tags. Exercise the union."""
    await _insert_wp_event(
        db_session,
        post_id=1,
        slug="her2-conversation",
        categories=["her2", "mbc"],
        tags=["adc-therapy", "practice-changing"],
        youtube_video_id="vid_A",
    )
    await _insert_wp_event(
        db_session,
        post_id=2,
        slug="hr-endocrine",
        categories=["hr", "mbc"],
        tags=["cdk46"],
        youtube_video_id="vid_B",
    )
    # A deleted post — MUST NOT contribute to the union.
    await _insert_wp_event(
        db_session,
        post_id=3,
        slug="obsolete",
        event="deleted",
        categories=["deprecated-topic"],
        tags=["deprecated-tag"],
    )
    # A subsequent-modified event for post 1 (should be the latest picked).
    await _insert_wp_event(
        db_session,
        post_id=1,
        slug="her2-conversation",
        modified_gmt=datetime.now(timezone.utc) + timedelta(hours=1),
        categories=["her2", "mbc", "cns"],  # cns added in the update
        tags=["adc-therapy", "practice-changing"],
        youtube_video_id="vid_A",
    )

    # Existing Clip.tags — should also be in the response.
    db_session.add(
        Clip(
            id="official:youtube:vid_A",
            title="HER2 conversation",
            channel="chm-official",
            tags=[
                "biomarker:HER2+",
                "doctor:Traina",
                "drug:T-DXd",
                "topic:existing-clip-topic",
            ],
        )
    )
    await db_session.flush()


@pytest.mark.asyncio
async def test_tags_projects_wp_categories_to_topic_namespace(
    client: AsyncClient, seeded_wp_and_clips
):
    r = await client.get("/api/public/tags", headers=api_headers())
    assert r.status_code == 200
    data = r.json()
    topics = set(data.get("topic", []))
    # WP categories (from both posts, latest per post_id) surfaced as topic:*
    assert "topic:her2" in topics
    assert "topic:mbc" in topics
    assert "topic:hr" in topics
    assert "topic:cns" in topics  # from the later update to post 1
    # Existing Clip.tags topic entry also present.
    assert "topic:existing-clip-topic" in topics


@pytest.mark.asyncio
async def test_tags_projects_wp_tags_to_wp_namespace(
    client: AsyncClient, seeded_wp_and_clips
):
    r = await client.get("/api/public/tags", headers=api_headers())
    data = r.json()
    wp = set(data.get("wp", []))
    assert "wp:adc-therapy" in wp
    assert "wp:practice-changing" in wp
    assert "wp:cdk46" in wp


@pytest.mark.asyncio
async def test_tags_deleted_wp_events_excluded(
    client: AsyncClient, seeded_wp_and_clips
):
    r = await client.get("/api/public/tags", headers=api_headers())
    data = r.json()
    # The deleted post's category + tag MUST NOT appear.
    all_values = [v for values in data.values() for v in values]
    assert "topic:deprecated-topic" not in all_values
    assert "wp:deprecated-tag" not in all_values


@pytest.mark.asyncio
async def test_tags_clip_tags_still_present(
    client: AsyncClient, seeded_wp_and_clips
):
    r = await client.get("/api/public/tags", headers=api_headers())
    data = r.json()
    assert "biomarker:HER2+" in data.get("biomarker", [])
    assert "doctor:Traina" in data.get("doctor", [])
    assert "drug:T-DXd" in data.get("drug", [])


@pytest.mark.asyncio
async def test_tags_wp_only_still_returns_wp_namespaces(
    client: AsyncClient, db_session: AsyncSession
):
    """No clips, only WP events → topic: + wp: come from WP alone."""
    await _insert_wp_event(
        db_session,
        post_id=42,
        slug="wp-only",
        categories=["wp-only-topic"],
        tags=["wp-only-tag"],
    )
    await db_session.flush()

    r = await client.get("/api/public/tags", headers=api_headers())
    assert r.status_code == 200
    data = r.json()
    assert "topic:wp-only-topic" in data.get("topic", [])
    assert "wp:wp-only-tag" in data.get("wp", [])


@pytest.mark.asyncio
async def test_tags_empty_universe_returns_empty_object(client: AsyncClient):
    r = await client.get("/api/public/tags", headers=api_headers())
    assert r.status_code == 200
    assert r.json() == {}
