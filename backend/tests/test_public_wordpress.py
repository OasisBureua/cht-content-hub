"""Integration tests for /api/public/wordpress + /wordpress/categories.

Uses in-memory SQLite (via the standard test conftest). Seeds
`wordpress_events` via raw SQL because the ORM `JSONB` columns don't
auto-serialize Python lists on SQLite — raw inserts sidestep that
mismatch without changing production behavior.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import API_KEY, api_headers


# ─────────────────────────────────────────────────────────────────────────────
# Seed helpers
# ─────────────────────────────────────────────────────────────────────────────


async def _insert_event(
    db: AsyncSession,
    *,
    post_id: int,
    slug: str,
    title: str,
    event: str = "published",
    modified_gmt: datetime | None = None,
    categories: list[str] | None = None,
    tags: list[str] | None = None,
    youtube_video_id: str | None = None,
    featured_media_url: str | None = None,
    permalink: str | None = None,
) -> None:
    modified_gmt = modified_gmt or datetime.now(timezone.utc)
    permalink = permalink or f"https://communityhealth.media/{slug}/"
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
                :youtube_video_id, :featured_media_url
            )
            """
        ),
        {
            "post_id": post_id,
            "modified_gmt": modified_gmt,
            "event": event,
            "slug": slug,
            "title": title,
            "permalink": permalink,
            "categories": json.dumps(categories or []),
            "tags": json.dumps(tags or []),
            "raw_payload": json.dumps({"post_id": post_id, "slug": slug}),
            "received_at": modified_gmt,
            "youtube_video_id": youtube_video_id,
            "featured_media_url": featured_media_url,
        },
    )


@pytest.fixture
async def seeded_wordpress(db_session: AsyncSession):
    """Seed a spread of WP events covering: multi-category, HP-prefixed slugs,
    delete-supersedes-publish, update chain, and posts without YouTube.
    """
    base = datetime(2026, 7, 1, tzinfo=timezone.utc)

    # 3 currently-live posts across different categories
    await _insert_event(
        db_session,
        post_id=101,
        slug="her2-esmo-2026",
        title="HER2 Highlights ESMO 2026",
        modified_gmt=base,
        categories=["her2", "ebc"],
        tags=["kol-video"],
        youtube_video_id="dQw4w9WgXcQ",
        featured_media_url="https://communityhealth.media/wp-content/her2.jpg",
    )
    await _insert_event(
        db_session,
        post_id=102,
        slug="hp-cns-mets",
        title="CNS Mets Update",
        modified_gmt=base + timedelta(days=1),
        categories=["her2", "cns"],
        tags=["conference-recap"],
        youtube_video_id="abcdefghijk",
    )
    await _insert_event(
        db_session,
        post_id=103,
        slug="lung-egfr-primer",
        title="EGFR Lung Primer",
        modified_gmt=base + timedelta(days=2),
        categories=["lung", "egfr"],
        tags=["kol-video"],
        # No YouTube embed — Vimeo or native upload
    )

    # Post 104: publish → update — update should win
    await _insert_event(
        db_session,
        post_id=104,
        slug="draft-title",
        title="Draft Title",
        modified_gmt=base,
        event="published",
        categories=["her2"],
    )
    await _insert_event(
        db_session,
        post_id=104,
        slug="final-title",
        title="Final Title",
        modified_gmt=base + timedelta(days=3),
        event="updated",
        categories=["her2", "trastuzumab"],
        youtube_video_id="updatedvid1",
    )

    # Post 105: publish → delete — should NOT appear
    await _insert_event(
        db_session,
        post_id=105,
        slug="deleted-post",
        title="Deleted Post",
        modified_gmt=base,
        event="published",
        categories=["her2"],
    )
    await _insert_event(
        db_session,
        post_id=105,
        slug="deleted-post",
        title="Deleted Post",
        modified_gmt=base + timedelta(days=4),
        event="deleted",
        categories=["her2"],
    )

    await db_session.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Auth — /categories
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_categories_requires_api_key(http_client: AsyncClient):
    response = await http_client.get("/api/public/wordpress/categories")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_categories_rejects_invalid_api_key(http_client: AsyncClient):
    response = await http_client.get(
        "/api/public/wordpress/categories",
        headers={"X-API-Key": "wrong"},
    )
    assert response.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# /categories behavior
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_categories_empty_when_no_events(client: AsyncClient):
    response = await client.get(
        "/api/public/wordpress/categories", headers=api_headers()
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {"items": [], "total": 0}


@pytest.mark.asyncio
async def test_categories_counts_current_state(
    client: AsyncClient, seeded_wordpress
):
    response = await client.get(
        "/api/public/wordpress/categories", headers=api_headers()
    )
    assert response.status_code == 200
    body = response.json()

    # Deleted post 105 must not contribute; updated post 104 contributes with
    # its post-update categories (her2 + trastuzumab).
    by_slug = {item["slug"]: item["post_count"] for item in body["items"]}

    # her2 posts currently live: 101, 102, 104 → 3
    assert by_slug["her2"] == 3
    # ebc: 101
    assert by_slug["ebc"] == 1
    # cns: 102
    assert by_slug["cns"] == 1
    # lung + egfr: 103
    assert by_slug["lung"] == 1
    assert by_slug["egfr"] == 1
    # trastuzumab: 104 (only after the update)
    assert by_slug["trastuzumab"] == 1

    # Slugs from post 105 (deleted) must not appear as standalone entries with
    # a count from post 105.
    # total = distinct slug count
    assert body["total"] == len(by_slug)


@pytest.mark.asyncio
async def test_categories_ordered_by_count_desc_then_slug_asc(
    client: AsyncClient, seeded_wordpress
):
    response = await client.get(
        "/api/public/wordpress/categories", headers=api_headers()
    )
    items = response.json()["items"]

    # Highest count first
    counts = [item["post_count"] for item in items]
    assert counts == sorted(counts, reverse=True)

    # Ties broken by slug asc — all slugs with the same count should be alpha
    from itertools import groupby

    for _, group in groupby(items, key=lambda x: x["post_count"]):
        slugs = [x["slug"] for x in group]
        assert slugs == sorted(slugs)


# ─────────────────────────────────────────────────────────────────────────────
# Auth — /wordpress list
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wordpress_list_requires_api_key(http_client: AsyncClient):
    response = await http_client.get("/api/public/wordpress")
    assert response.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# /wordpress list behavior
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wordpress_list_empty(client: AsyncClient):
    response = await client.get("/api/public/wordpress", headers=api_headers())
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}
    assert response.headers["X-Total-Count"] == "0"


@pytest.mark.asyncio
async def test_wordpress_list_returns_latest_non_deleted_per_post(
    client: AsyncClient, seeded_wordpress
):
    response = await client.get("/api/public/wordpress", headers=api_headers())
    assert response.status_code == 200
    body = response.json()

    post_ids = {item["post_id"] for item in body["items"]}
    # Live: 101, 102, 103, 104. Deleted: 105 must be absent.
    assert post_ids == {101, 102, 103, 104}
    assert body["total"] == 4
    assert response.headers["X-Total-Count"] == "4"

    # Post 104 should reflect the UPDATE (Final Title / trastuzumab), not the publish.
    p104 = next(item for item in body["items"] if item["post_id"] == 104)
    assert p104["title"] == "Final Title"
    assert p104["slug"] == "final-title"
    assert "trastuzumab" in p104["categories"]
    assert p104["youtube_video_id"] == "updatedvid1"


@pytest.mark.asyncio
async def test_wordpress_list_ordered_by_modified_gmt_desc(
    client: AsyncClient, seeded_wordpress
):
    response = await client.get("/api/public/wordpress", headers=api_headers())
    items = response.json()["items"]
    modifieds = [item["modified_gmt"] for item in items]
    assert modifieds == sorted(modifieds, reverse=True)


@pytest.mark.asyncio
async def test_wordpress_list_filter_by_category(
    client: AsyncClient, seeded_wordpress
):
    response = await client.get(
        "/api/public/wordpress?category=her2", headers=api_headers()
    )
    assert response.status_code == 200
    body = response.json()
    post_ids = {item["post_id"] for item in body["items"]}
    # 101, 102, 104 all have her2 currently. 103 (lung/egfr) does not.
    assert post_ids == {101, 102, 104}


@pytest.mark.asyncio
async def test_wordpress_list_filter_by_tag(
    client: AsyncClient, seeded_wordpress
):
    response = await client.get(
        "/api/public/wordpress?tag=kol-video", headers=api_headers()
    )
    body = response.json()
    post_ids = {item["post_id"] for item in body["items"]}
    assert post_ids == {101, 103}


@pytest.mark.asyncio
async def test_wordpress_list_filter_has_youtube(
    client: AsyncClient, seeded_wordpress
):
    response = await client.get(
        "/api/public/wordpress?has_youtube=true", headers=api_headers()
    )
    body = response.json()
    post_ids = {item["post_id"] for item in body["items"]}
    # 101, 102, 104 have YouTube IDs. 103 does not.
    assert post_ids == {101, 102, 104}


@pytest.mark.asyncio
async def test_wordpress_list_pagination(
    client: AsyncClient, seeded_wordpress
):
    r1 = await client.get(
        "/api/public/wordpress?limit=2&offset=0", headers=api_headers()
    )
    r2 = await client.get(
        "/api/public/wordpress?limit=2&offset=2", headers=api_headers()
    )
    assert r1.headers["X-Total-Count"] == "4"
    assert r2.headers["X-Total-Count"] == "4"
    assert len(r1.json()["items"]) == 2
    assert len(r2.json()["items"]) == 2

    ids_page1 = {i["post_id"] for i in r1.json()["items"]}
    ids_page2 = {i["post_id"] for i in r2.json()["items"]}
    assert ids_page1.isdisjoint(ids_page2)


@pytest.mark.asyncio
async def test_wordpress_list_since_filter(
    client: AsyncClient, seeded_wordpress
):
    # base = 2026-07-01. Post 104's update happened base+3 = 2026-07-04.
    # since=2026-07-04 should only return post 104 (and nothing else).
    response = await client.get(
        "/api/public/wordpress?since=2026-07-04T00:00:00Z", headers=api_headers()
    )
    body = response.json()
    post_ids = {item["post_id"] for item in body["items"]}
    assert post_ids == {104}
