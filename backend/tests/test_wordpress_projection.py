"""Tests for the WordPress Layer 2 projection module + endpoints.

Covers:
- Post-event projection into wordpress_posts + M:M association tables
- Term-event projection into wordpress_series / _categories / _tags
- Delete tombstone semantics (`deleted_at` set, associations preserved)
- Out-of-order webhook delivery
- Resurrection (delete then re-publish)
- Idempotency (replay produces zero net change)
- Series list + detail endpoints
- Refactored /categories + /tags + /wordpress endpoints hitting Layer 2

Uses the shared `_insert_event` helper from test_public_wordpress, which
seeds Layer 1 AND projects to Layer 2 — same code path as production ingest.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import api_headers
from jobs.wordpress_ingest_projection import (
    project_post_event,
    project_term_event,
)
from models.wordpress_projection import (
    WordPressCategory,
    WordPressPost,
    WordPressPostCategory,
    WordPressPostSeries,
    WordPressPostTag,
    WordPressSeries,
    WordPressTag,
)

# Re-use the seed helper (seeds Layer 1 + projects to Layer 2).
from tests.test_public_wordpress import _insert_event


# ─────────────────────────────────────────────────────────────────────────────
# Post-event projection: UPSERT + M:M reconcile
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_creates_post_and_terms_and_memberships(
    db_session: AsyncSession,
):
    await _insert_event(
        db_session,
        post_id=1001,
        slug="post-a",
        title="Post A",
        categories=["her2", "ebc"],
        tags=["kol-video"],
        series=["dr-iyengar-dr-hurvitz"],
    )
    await db_session.commit()

    # wordpress_posts row exists.
    post = (
        await db_session.execute(
            select(WordPressPost).where(WordPressPost.post_id == 1001)
        )
    ).scalar_one()
    assert post.title == "Post A"
    assert post.deleted_at is None

    # Term rows created with slug-only defaults.
    her2 = (
        await db_session.execute(
            select(WordPressCategory).where(WordPressCategory.slug == "her2")
        )
    ).scalar_one()
    assert her2.name == "her2"  # slug-as-name placeholder
    assert her2.wp_term_id is None

    # M:M memberships correct.
    cat_slugs = set(
        (
            await db_session.execute(
                select(WordPressPostCategory.category_slug).where(
                    WordPressPostCategory.post_id == 1001
                )
            )
        ).scalars()
    )
    assert cat_slugs == {"her2", "ebc"}

    series_slugs = set(
        (
            await db_session.execute(
                select(WordPressPostSeries.series_slug).where(
                    WordPressPostSeries.post_id == 1001
                )
            )
        ).scalars()
    )
    assert series_slugs == {"dr-iyengar-dr-hurvitz"}


@pytest.mark.asyncio
async def test_update_reconciles_membership_additions_and_removals(
    db_session: AsyncSession,
):
    base = datetime(2026, 7, 20, tzinfo=timezone.utc)
    # Initial publish.
    await _insert_event(
        db_session,
        post_id=1002,
        slug="post-b",
        title="Post B",
        modified_gmt=base,
        categories=["her2"],
        tags=["kol-video", "expert-panel"],
    )
    # Update: adds a category, drops a tag.
    await _insert_event(
        db_session,
        post_id=1002,
        slug="post-b",
        title="Post B v2",
        modified_gmt=base + timedelta(days=1),
        event="updated",
        categories=["her2", "ebc"],
        tags=["kol-video"],  # expert-panel dropped
    )
    await db_session.commit()

    cat_slugs = set(
        (
            await db_session.execute(
                select(WordPressPostCategory.category_slug).where(
                    WordPressPostCategory.post_id == 1002
                )
            )
        ).scalars()
    )
    tag_slugs = set(
        (
            await db_session.execute(
                select(WordPressPostTag.tag_slug).where(
                    WordPressPostTag.post_id == 1002
                )
            )
        ).scalars()
    )
    assert cat_slugs == {"her2", "ebc"}
    assert tag_slugs == {"kol-video"}


@pytest.mark.asyncio
async def test_delete_tombstones_post_and_preserves_memberships(
    db_session: AsyncSession,
):
    """Delete sets deleted_at but leaves M:M rows in place.

    Read endpoints filter by deleted_at IS NULL, so deleted posts become
    invisible; audit queries can still walk membership history.
    """
    base = datetime(2026, 7, 20, tzinfo=timezone.utc)
    await _insert_event(
        db_session,
        post_id=1003,
        slug="doomed",
        title="Doomed",
        modified_gmt=base,
        categories=["her2"],
        series=["some-series"],
    )
    await _insert_event(
        db_session,
        post_id=1003,
        slug="doomed",
        title="Doomed",
        modified_gmt=base + timedelta(days=1),
        event="deleted",
        categories=["her2"],
        series=["some-series"],
    )
    await db_session.commit()

    post = (
        await db_session.execute(
            select(WordPressPost).where(WordPressPost.post_id == 1003)
        )
    ).scalar_one()
    assert post.deleted_at is not None

    # Memberships preserved (tombstone pattern).
    cat_count = len(
        (
            await db_session.execute(
                select(WordPressPostCategory).where(
                    WordPressPostCategory.post_id == 1003
                )
            )
        ).scalars().all()
    )
    assert cat_count == 1


@pytest.mark.asyncio
async def test_resurrection_clears_deleted_at(db_session: AsyncSession):
    """Delete then re-publish clears the tombstone."""
    base = datetime(2026, 7, 20, tzinfo=timezone.utc)
    await _insert_event(
        db_session,
        post_id=1004,
        slug="phoenix",
        title="Phoenix",
        modified_gmt=base,
    )
    await _insert_event(
        db_session,
        post_id=1004,
        slug="phoenix",
        title="Phoenix",
        modified_gmt=base + timedelta(days=1),
        event="deleted",
    )
    # Re-publish (Andrew undeletes / republishes).
    await _insert_event(
        db_session,
        post_id=1004,
        slug="phoenix-reborn",
        title="Phoenix Reborn",
        modified_gmt=base + timedelta(days=2),
        event="published",
    )
    await db_session.commit()

    post = (
        await db_session.execute(
            select(WordPressPost).where(WordPressPost.post_id == 1004)
        )
    ).scalar_one()
    assert post.deleted_at is None
    assert post.slug == "phoenix-reborn"


@pytest.mark.asyncio
async def test_out_of_order_event_does_not_overwrite_newer_state(
    db_session: AsyncSession,
):
    """A late-arriving `updated` event with older modified_gmt is ignored.

    SQS re-delivery + batching can produce out-of-order events for the same
    post. The projection guards against this by comparing modified_gmt.
    """
    base = datetime(2026, 7, 20, tzinfo=timezone.utc)
    # New event first.
    await _insert_event(
        db_session,
        post_id=1005,
        slug="latest",
        title="Latest Title",
        modified_gmt=base + timedelta(days=1),
        event="updated",
    )
    # Older event arrives late.
    await _insert_event(
        db_session,
        post_id=1005,
        slug="older",
        title="Older Title",
        modified_gmt=base,
        event="published",
    )
    await db_session.commit()

    post = (
        await db_session.execute(
            select(WordPressPost).where(WordPressPost.post_id == 1005)
        )
    ).scalar_one()
    # Newer state wins.
    assert post.title == "Latest Title"
    assert post.slug == "latest"


@pytest.mark.asyncio
async def test_replay_is_idempotent(db_session: AsyncSession):
    """Projecting the same event twice produces zero net change."""
    base = datetime(2026, 7, 20, tzinfo=timezone.utc)
    payload = {
        "event": "published",
        "post_id": 1006,
        "post_type": "post",
        "slug": "idempotent",
        "title": "Idempotent",
        "status": "publish",
        "modified_gmt": base,
        "permalink": "https://communityhealth.media/idempotent/",
        "categories": ["her2", "ebc"],
        "tags": ["kol-video"],
        "series": ["some-series"],
    }
    # Two projections against a fake event_id — should be idempotent even
    # if we cheat and reuse event_id since we're testing the projection.
    await project_post_event(db_session, payload, event_id=999)
    await project_post_event(db_session, payload, event_id=999)
    await db_session.commit()

    cat_rows = (
        await db_session.execute(
            select(WordPressPostCategory).where(
                WordPressPostCategory.post_id == 1006
            )
        )
    ).scalars().all()
    # Exactly 2 category rows (her2 + ebc) — not 4 (no duplicates).
    assert len(cat_rows) == 2

    post_count = len(
        (
            await db_session.execute(
                select(WordPressPost).where(WordPressPost.post_id == 1006)
            )
        ).scalars().all()
    )
    assert post_count == 1


@pytest.mark.asyncio
async def test_delete_before_publish_creates_tombstone(
    db_session: AsyncSession,
):
    """Out-of-order: delete arrives before any publish for this post_id.

    Rare — but must not fail. Ingest creates a minimal tombstone row.
    """
    payload = {
        "event": "deleted",
        "post_id": 9999,
        "post_type": "post",
        "slug": "missing",
        "title": "Missing",
        "status": "trash",
        "modified_gmt": datetime.now(timezone.utc),
        "permalink": "",
        "categories": [],
        "tags": [],
        "series": [],
    }
    await project_post_event(db_session, payload, event_id=1234)
    await db_session.commit()

    post = (
        await db_session.execute(
            select(WordPressPost).where(WordPressPost.post_id == 9999)
        )
    ).scalar_one()
    assert post.deleted_at is not None


# ─────────────────────────────────────────────────────────────────────────────
# Term-event projection
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_term_updated_creates_series_row_with_metadata(
    db_session: AsyncSession,
):
    payload = {
        "event": "term_updated",
        "taxonomy": "series",
        "term_id": 42,
        "slug": "dr-iyengar-dr-hurvitz",
        "name": "Drs. Iyengar & Hurvitz",
        "description": "Doctor-pair episodes",
        "parent_slug": None,
    }
    await project_term_event(db_session, payload)
    await db_session.commit()

    series = (
        await db_session.execute(
            select(WordPressSeries).where(
                WordPressSeries.slug == "dr-iyengar-dr-hurvitz"
            )
        )
    ).scalar_one()
    assert series.name == "Drs. Iyengar & Hurvitz"
    assert series.description == "Doctor-pair episodes"
    assert series.wp_term_id == 42


@pytest.mark.asyncio
async def test_term_updated_upserts_existing_row(db_session: AsyncSession):
    """Second term_updated event overwrites metadata, keeps first_seen."""
    payload_v1 = {
        "event": "term_updated",
        "taxonomy": "series",
        "term_id": 42,
        "slug": "renamed-series",
        "name": "Original Name",
    }
    payload_v2 = {
        "event": "term_updated",
        "taxonomy": "series",
        "term_id": 42,
        "slug": "renamed-series",
        "name": "Better Name",
        "description": "Now with a description",
    }
    await project_term_event(db_session, payload_v1)
    await db_session.commit()

    first_seen_before = (
        await db_session.execute(
            select(WordPressSeries.first_seen).where(
                WordPressSeries.slug == "renamed-series"
            )
        )
    ).scalar_one()

    await project_term_event(db_session, payload_v2)
    await db_session.commit()

    row = (
        await db_session.execute(
            select(WordPressSeries).where(
                WordPressSeries.slug == "renamed-series"
            )
        )
    ).scalar_one()
    assert row.name == "Better Name"
    assert row.description == "Now with a description"
    assert row.first_seen == first_seen_before  # preserved


@pytest.mark.asyncio
async def test_term_updated_enriches_placeholder_row(db_session: AsyncSession):
    """Post event created slug-only placeholder; term event fills in metadata."""
    await _insert_event(
        db_session,
        post_id=2001,
        slug="post-x",
        title="Post X",
        series=["placeholder-series"],
    )
    await db_session.commit()

    row = (
        await db_session.execute(
            select(WordPressSeries).where(
                WordPressSeries.slug == "placeholder-series"
            )
        )
    ).scalar_one()
    assert row.name == "placeholder-series"  # placeholder

    payload = {
        "event": "term_updated",
        "taxonomy": "series",
        "term_id": 99,
        "slug": "placeholder-series",
        "name": "Real Display Name",
        "description": "Backfilled from term webhook",
    }
    await project_term_event(db_session, payload)
    await db_session.commit()

    row = (
        await db_session.execute(
            select(WordPressSeries).where(
                WordPressSeries.slug == "placeholder-series"
            )
        )
    ).scalar_one()
    assert row.name == "Real Display Name"
    assert row.wp_term_id == 99


@pytest.mark.asyncio
async def test_term_deleted_tombstones_row(db_session: AsyncSession):
    await project_term_event(
        db_session,
        {
            "event": "term_updated",
            "taxonomy": "category",
            "term_id": 5,
            "slug": "retired-category",
            "name": "Retired",
        },
    )
    await db_session.commit()

    await project_term_event(
        db_session,
        {
            "event": "term_deleted",
            "taxonomy": "category",
            "term_id": 5,
            "slug": "retired-category",
        },
    )
    await db_session.commit()

    row = (
        await db_session.execute(
            select(WordPressCategory).where(
                WordPressCategory.slug == "retired-category"
            )
        )
    ).scalar_one()
    assert row.deleted_at is not None


@pytest.mark.asyncio
async def test_term_deleted_for_unknown_term_is_noop(
    db_session: AsyncSession,
):
    """Deleting a term we've never seen must not crash — pre-webhook history
    gap is a real scenario."""
    await project_term_event(
        db_session,
        {
            "event": "term_deleted",
            "taxonomy": "series",
            "term_id": 88,
            "slug": "never-seen",
        },
    )
    await db_session.commit()

    row = (
        await db_session.execute(
            select(WordPressSeries).where(
                WordPressSeries.slug == "never-seen"
            )
        )
    ).scalar_one_or_none()
    assert row is None


@pytest.mark.asyncio
async def test_term_event_unknown_taxonomy_raises(db_session: AsyncSession):
    """Router should already reject at shape check; projection is defensive."""
    with pytest.raises(ValueError, match="unknown taxonomy"):
        await project_term_event(
            db_session,
            {
                "event": "term_updated",
                "taxonomy": "not-real",
                "term_id": 1,
                "slug": "whatever",
                "name": "Whatever",
            },
        )


# ─────────────────────────────────────────────────────────────────────────────
# /series list + detail endpoints
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_series_list_requires_api_key(http_client: AsyncClient):
    response = await http_client.get("/api/public/wordpress/series")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_series_list_empty(client: AsyncClient):
    response = await client.get(
        "/api/public/wordpress/series", headers=api_headers()
    )
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


@pytest.mark.asyncio
async def test_series_list_returns_terms_with_counts(
    client: AsyncClient, db_session: AsyncSession
):
    base = datetime(2026, 7, 20, tzinfo=timezone.utc)
    await _insert_event(
        db_session,
        post_id=3001,
        slug="a",
        title="A",
        modified_gmt=base,
        series=["popular-series", "quiet-series"],
    )
    await _insert_event(
        db_session,
        post_id=3002,
        slug="b",
        title="B",
        modified_gmt=base + timedelta(days=1),
        series=["popular-series"],
    )
    await _insert_event(
        db_session,
        post_id=3003,
        slug="c",
        title="C",
        modified_gmt=base + timedelta(days=2),
        series=["popular-series"],
    )
    # Enrich the "popular-series" term with real name via term event.
    await project_term_event(
        db_session,
        {
            "event": "term_updated",
            "taxonomy": "series",
            "term_id": 10,
            "slug": "popular-series",
            "name": "Popular Series",
        },
    )
    await db_session.commit()

    response = await client.get(
        "/api/public/wordpress/series", headers=api_headers()
    )
    assert response.status_code == 200
    body = response.json()
    by_slug = {item["slug"]: item for item in body["items"]}

    assert by_slug["popular-series"]["post_count"] == 3
    assert by_slug["popular-series"]["name"] == "Popular Series"
    assert by_slug["quiet-series"]["post_count"] == 1

    # Ordered by count desc.
    counts = [item["post_count"] for item in body["items"]]
    assert counts == sorted(counts, reverse=True)


@pytest.mark.asyncio
async def test_series_list_excludes_empty_and_deleted_terms(
    client: AsyncClient, db_session: AsyncSession
):
    base = datetime(2026, 7, 20, tzinfo=timezone.utc)
    # Live series with a live post.
    await _insert_event(
        db_session,
        post_id=3010,
        slug="live",
        title="Live",
        modified_gmt=base,
        series=["live-series"],
    )
    # Series with only a deleted post → should not appear (count=0).
    await _insert_event(
        db_session,
        post_id=3011,
        slug="deleted-post",
        title="Deleted Post",
        modified_gmt=base,
        series=["empty-series"],
    )
    await _insert_event(
        db_session,
        post_id=3011,
        slug="deleted-post",
        title="Deleted Post",
        modified_gmt=base + timedelta(days=1),
        event="deleted",
        series=["empty-series"],
    )
    # Tombstoned series term.
    await project_term_event(
        db_session,
        {
            "event": "term_updated",
            "taxonomy": "series",
            "term_id": 20,
            "slug": "tombstone-series",
            "name": "Tombstone",
        },
    )
    await project_term_event(
        db_session,
        {
            "event": "term_deleted",
            "taxonomy": "series",
            "term_id": 20,
            "slug": "tombstone-series",
        },
    )
    await db_session.commit()

    response = await client.get(
        "/api/public/wordpress/series", headers=api_headers()
    )
    slugs = {item["slug"] for item in response.json()["items"]}
    assert "live-series" in slugs
    assert "empty-series" not in slugs
    assert "tombstone-series" not in slugs


@pytest.mark.asyncio
async def test_series_detail_returns_metadata_and_post_ids(
    client: AsyncClient, db_session: AsyncSession
):
    base = datetime(2026, 7, 20, tzinfo=timezone.utc)
    await _insert_event(
        db_session,
        post_id=3020,
        slug="p1",
        title="P1",
        modified_gmt=base,
        series=["target-series"],
    )
    await _insert_event(
        db_session,
        post_id=3021,
        slug="p2",
        title="P2",
        modified_gmt=base + timedelta(days=1),
        series=["target-series"],
    )
    await project_term_event(
        db_session,
        {
            "event": "term_updated",
            "taxonomy": "series",
            "term_id": 30,
            "slug": "target-series",
            "name": "Target Series",
            "description": "Full detail test",
        },
    )
    await db_session.commit()

    response = await client.get(
        "/api/public/wordpress/series/target-series", headers=api_headers()
    )
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "target-series"
    assert body["name"] == "Target Series"
    assert body["description"] == "Full detail test"
    assert body["post_count"] == 2
    assert set(body["post_ids"]) == {3020, 3021}


@pytest.mark.asyncio
async def test_series_detail_excludes_deleted_posts_from_post_ids(
    client: AsyncClient, db_session: AsyncSession
):
    base = datetime(2026, 7, 20, tzinfo=timezone.utc)
    await _insert_event(
        db_session,
        post_id=3030,
        slug="live",
        title="Live",
        modified_gmt=base,
        series=["mixed-series"],
    )
    await _insert_event(
        db_session,
        post_id=3031,
        slug="doomed",
        title="Doomed",
        modified_gmt=base,
        series=["mixed-series"],
    )
    await _insert_event(
        db_session,
        post_id=3031,
        slug="doomed",
        title="Doomed",
        modified_gmt=base + timedelta(days=1),
        event="deleted",
        series=["mixed-series"],
    )
    await project_term_event(
        db_session,
        {
            "event": "term_updated",
            "taxonomy": "series",
            "term_id": 31,
            "slug": "mixed-series",
            "name": "Mixed",
        },
    )
    await db_session.commit()

    response = await client.get(
        "/api/public/wordpress/series/mixed-series", headers=api_headers()
    )
    body = response.json()
    # Live post appears; deleted post excluded.
    assert body["post_count"] == 1
    assert body["post_ids"] == [3030]


@pytest.mark.asyncio
async def test_series_detail_404_for_unknown_slug(client: AsyncClient):
    response = await client.get(
        "/api/public/wordpress/series/does-not-exist", headers=api_headers()
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_series_detail_404_for_tombstoned_slug(
    client: AsyncClient, db_session: AsyncSession
):
    await project_term_event(
        db_session,
        {
            "event": "term_updated",
            "taxonomy": "series",
            "term_id": 40,
            "slug": "gone",
            "name": "Gone",
        },
    )
    await project_term_event(
        db_session,
        {
            "event": "term_deleted",
            "taxonomy": "series",
            "term_id": 40,
            "slug": "gone",
        },
    )
    await db_session.commit()

    response = await client.get(
        "/api/public/wordpress/series/gone", headers=api_headers()
    )
    assert response.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# /tags list — new endpoint mirrors /series shape
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# WPR-8 — series slug rename + alias handling
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_series_rename_moves_master_and_memberships(
    db_session: AsyncSession,
):
    """A term_updated event carrying same wp_term_id + new slug is a rename.
    The master wordpress_series row's slug updates, M:M memberships move to
    the new slug, and a slug_alias row records the old slug for redirects."""
    from models.wordpress_projection import WordPressSeriesSlugAlias

    # Seed original series.
    await project_term_event(
        db_session,
        {
            "event": "term_updated",
            "taxonomy": "series",
            "term_id": 500,
            "slug": "old-slug",
            "name": "Old Name",
        },
    )
    # Attach a post to the original series.
    await _insert_event(
        db_session,
        post_id=5001,
        slug="p",
        title="P",
        series=["old-slug"],
    )
    await db_session.commit()

    # Rename event.
    await project_term_event(
        db_session,
        {
            "event": "term_updated",
            "taxonomy": "series",
            "term_id": 500,
            "slug": "new-slug",
            "name": "New Name",
        },
    )
    await db_session.commit()

    # Master row now has the new slug.
    series_row = (
        await db_session.execute(
            select(WordPressSeries).where(WordPressSeries.wp_term_id == 500)
        )
    ).scalar_one()
    assert series_row.slug == "new-slug"
    assert series_row.name == "New Name"

    # Old slug no longer exists as a series row.
    old_row = (
        await db_session.execute(
            select(WordPressSeries).where(WordPressSeries.slug == "old-slug")
        )
    ).scalar_one_or_none()
    assert old_row is None

    # M:M association moved.
    membership_slugs = set(
        (
            await db_session.execute(
                select(WordPressPostSeries.series_slug).where(
                    WordPressPostSeries.post_id == 5001
                )
            )
        ).scalars()
    )
    assert membership_slugs == {"new-slug"}

    # Alias row records the redirect.
    alias = (
        await db_session.execute(
            select(WordPressSeriesSlugAlias).where(
                WordPressSeriesSlugAlias.old_slug == "old-slug"
            )
        )
    ).scalar_one()
    assert alias.current_slug == "new-slug"


@pytest.mark.asyncio
async def test_series_chained_rename_collapses_alias_hops(
    db_session: AsyncSession,
):
    """A → B → C should result in two alias rows both pointing at C."""
    from models.wordpress_projection import WordPressSeriesSlugAlias

    await project_term_event(
        db_session,
        {"event": "term_updated", "taxonomy": "series", "term_id": 600,
         "slug": "a", "name": "A"},
    )
    await project_term_event(
        db_session,
        {"event": "term_updated", "taxonomy": "series", "term_id": 600,
         "slug": "b", "name": "B"},
    )
    await project_term_event(
        db_session,
        {"event": "term_updated", "taxonomy": "series", "term_id": 600,
         "slug": "c", "name": "C"},
    )
    await db_session.commit()

    aliases = (
        await db_session.execute(select(WordPressSeriesSlugAlias))
    ).scalars().all()
    by_old = {a.old_slug: a.current_slug for a in aliases}
    # Both `a` and `b` should point at `c` (transitive fix).
    assert by_old.get("a") == "c"
    assert by_old.get("b") == "c"


@pytest.mark.asyncio
async def test_series_detail_301_redirects_old_slug_to_current(
    client: AsyncClient, db_session: AsyncSession
):
    """Requests for the old slug get a 301 to the current slug."""
    await project_term_event(
        db_session,
        {"event": "term_updated", "taxonomy": "series", "term_id": 700,
         "slug": "renamed-old", "name": "Renamed Old"},
    )
    await project_term_event(
        db_session,
        {"event": "term_updated", "taxonomy": "series", "term_id": 700,
         "slug": "renamed-new", "name": "Renamed New"},
    )
    await db_session.commit()

    response = await client.get(
        "/api/public/wordpress/series/renamed-old",
        headers=api_headers(),
        follow_redirects=False,
    )
    assert response.status_code == 301
    assert (
        response.headers.get("location")
        == "/api/public/wordpress/series/renamed-new"
    )


@pytest.mark.asyncio
async def test_category_rename_moves_master_and_memberships_no_alias(
    db_session: AsyncSession,
):
    """Category renames work the same way but don't get an alias table row —
    WPR-8 scope is series only."""
    from models.wordpress_projection import WordPressSeriesSlugAlias

    await project_term_event(
        db_session,
        {"event": "term_updated", "taxonomy": "category", "term_id": 800,
         "slug": "old-cat", "name": "Old Cat"},
    )
    await _insert_event(
        db_session,
        post_id=5010,
        slug="p2",
        title="P2",
        categories=["old-cat"],
    )
    await db_session.commit()

    await project_term_event(
        db_session,
        {"event": "term_updated", "taxonomy": "category", "term_id": 800,
         "slug": "new-cat", "name": "New Cat"},
    )
    await db_session.commit()

    cat_row = (
        await db_session.execute(
            select(WordPressCategory).where(WordPressCategory.wp_term_id == 800)
        )
    ).scalar_one()
    assert cat_row.slug == "new-cat"

    membership_slugs = set(
        (
            await db_session.execute(
                select(WordPressPostCategory.category_slug).where(
                    WordPressPostCategory.post_id == 5010
                )
            )
        ).scalars()
    )
    assert membership_slugs == {"new-cat"}

    # Alias table is series-only — should NOT record a category rename.
    aliases = (
        await db_session.execute(select(WordPressSeriesSlugAlias))
    ).scalars().all()
    # Only aliases from other tests could exist; this rename must not add one.
    assert not any(a.old_slug == "old-cat" for a in aliases)


@pytest.mark.asyncio
async def test_tags_list_returns_term_metadata(
    client: AsyncClient, db_session: AsyncSession
):
    base = datetime(2026, 7, 20, tzinfo=timezone.utc)
    await _insert_event(
        db_session,
        post_id=4001,
        slug="a",
        title="A",
        modified_gmt=base,
        tags=["her2-positive"],
    )
    await project_term_event(
        db_session,
        {
            "event": "term_updated",
            "taxonomy": "post_tag",
            "term_id": 100,
            "slug": "her2-positive",
            "name": "HER2 Positive",
            "description": "HER2+ breast cancer",
        },
    )
    await db_session.commit()

    response = await client.get(
        "/api/public/wordpress/tags", headers=api_headers()
    )
    body = response.json()
    her2 = next(item for item in body["items"] if item["slug"] == "her2-positive")
    assert her2["name"] == "HER2 Positive"
    assert her2["description"] == "HER2+ breast cancer"
    assert her2["post_count"] == 1
