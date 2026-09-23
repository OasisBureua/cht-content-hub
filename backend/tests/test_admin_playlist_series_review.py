"""Tests for admin playlist ↔ series review-queue API (WPR-6)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import api_headers
from models.playlist_series_match_review import PlaylistSeriesMatchReview
from models.playlist_tag import PlaylistTag
from models.wordpress_projection import WordPressSeries


@pytest.fixture
async def seeded_series(db_session: AsyncSession) -> WordPressSeries:
    row = WordPressSeries(
        slug="dr-a-dr-b",
        name="Drs. A & B",
        description=None,
        parent_slug=None,
        wp_term_id=1,
    )
    db_session.add(row)
    await db_session.commit()
    return row


@pytest.fixture
async def pending_review(
    db_session: AsyncSession, seeded_series: WordPressSeries
) -> PlaylistSeriesMatchReview:
    row = PlaylistSeriesMatchReview(
        youtube_playlist_id="PL_target",
        wp_series_slug=seeded_series.slug,
        match_score=0.87,
        signals={"doctor_overlap": ["a", "b"], "title_similarity": 0.87},
        status="pending",
    )
    db_session.add(row)
    await db_session.commit()
    return row


# ─────────────────────────────────────────────────────────────────────────────
# List
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_requires_api_key(client: AsyncClient):
    r = await client.get("/api/admin/playlist-series-review")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_list_empty(client: AsyncClient):
    r = await client.get(
        "/api/admin/playlist-series-review", headers=api_headers()
    )
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0}


@pytest.mark.asyncio
async def test_list_filters_by_status(
    client: AsyncClient, pending_review, db_session: AsyncSession
):
    approved = PlaylistSeriesMatchReview(
        youtube_playlist_id="PL_other",
        wp_series_slug=pending_review.wp_series_slug,
        match_score=0.5,
        signals={},
        status="approved",
        reviewed_at=datetime.now(timezone.utc),
        reviewed_by="Sebastien",
    )
    db_session.add(approved)
    await db_session.commit()

    r = await client.get(
        "/api/admin/playlist-series-review?status=pending",
        headers=api_headers(),
    )
    assert r.json()["total"] == 1
    r = await client.get(
        "/api/admin/playlist-series-review?status=approved",
        headers=api_headers(),
    )
    assert r.json()["total"] == 1
    r = await client.get(
        "/api/admin/playlist-series-review?status=all", headers=api_headers()
    )
    assert r.json()["total"] == 2


@pytest.mark.asyncio
async def test_list_rejects_invalid_status(client: AsyncClient):
    r = await client.get(
        "/api/admin/playlist-series-review?status=weird",
        headers=api_headers(),
    )
    assert r.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# Create
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_inserts_pending_row(
    client: AsyncClient, seeded_series: WordPressSeries
):
    r = await client.post(
        "/api/admin/playlist-series-review",
        headers=api_headers(),
        json={
            "youtube_playlist_id": "PL_new",
            "wp_series_slug": seeded_series.slug,
            "match_score": 0.75,
            "signals": {"doctor_overlap": ["a"]},
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["youtube_playlist_id"] == "PL_new"
    assert body["status"] == "pending"
    assert body["match_score"] == 0.75


@pytest.mark.asyncio
async def test_create_rejects_unknown_series(client: AsyncClient):
    r = await client.post(
        "/api/admin/playlist-series-review",
        headers=api_headers(),
        json={
            "youtube_playlist_id": "PL_x",
            "wp_series_slug": "nonexistent-series",
            "match_score": 0.5,
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_duplicate_pending(
    client: AsyncClient, pending_review, seeded_series
):
    r = await client.post(
        "/api/admin/playlist-series-review",
        headers=api_headers(),
        json={
            "youtube_playlist_id": pending_review.youtube_playlist_id,
            "wp_series_slug": pending_review.wp_series_slug,
            "match_score": 0.9,
        },
    )
    assert r.status_code == 409


# ─────────────────────────────────────────────────────────────────────────────
# Approve
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approve_flips_status_and_upserts_playlist_tags(
    client: AsyncClient, pending_review, db_session: AsyncSession
):
    r = await client.post(
        f"/api/admin/playlist-series-review/{pending_review.id}/approve",
        headers=api_headers(),
        json={"reviewed_by": "Morgan"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved"
    assert body["reviewed_by"] == "Morgan"
    assert body["reviewed_at"] is not None

    # playlist_tags row exists and links to the series.
    pt = (
        await db_session.execute(
            select(PlaylistTag).where(
                PlaylistTag.youtube_playlist_id == pending_review.youtube_playlist_id
            )
        )
    ).scalar_one()
    assert pt.wp_series_slug == pending_review.wp_series_slug


@pytest.mark.asyncio
async def test_approve_updates_existing_playlist_tags(
    client: AsyncClient, pending_review, db_session: AsyncSession
):
    """Approve should preserve existing tags + lane while adding wp_series_slug."""
    pre = PlaylistTag(
        youtube_playlist_id=pending_review.youtube_playlist_id,
        tags=["biomarker:HER2+"],
        lane="biomarker",
    )
    db_session.add(pre)
    await db_session.commit()

    r = await client.post(
        f"/api/admin/playlist-series-review/{pending_review.id}/approve",
        headers=api_headers(),
        json={"reviewed_by": "Morgan"},
    )
    assert r.status_code == 200

    pt = (
        await db_session.execute(
            select(PlaylistTag).where(
                PlaylistTag.youtube_playlist_id == pending_review.youtube_playlist_id
            )
        )
    ).scalar_one()
    assert pt.wp_series_slug == pending_review.wp_series_slug
    assert pt.tags == ["biomarker:HER2+"]
    assert pt.lane == "biomarker"


@pytest.mark.asyncio
async def test_approve_404_for_unknown_review(client: AsyncClient):
    r = await client.post(
        "/api/admin/playlist-series-review/99999/approve",
        headers=api_headers(),
        json={"reviewed_by": "Morgan"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_approve_409_if_already_approved(
    client: AsyncClient, pending_review
):
    r1 = await client.post(
        f"/api/admin/playlist-series-review/{pending_review.id}/approve",
        headers=api_headers(),
        json={"reviewed_by": "Morgan"},
    )
    assert r1.status_code == 200
    r2 = await client.post(
        f"/api/admin/playlist-series-review/{pending_review.id}/approve",
        headers=api_headers(),
        json={"reviewed_by": "Morgan"},
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_approve_422_if_series_tombstoned(
    client: AsyncClient, pending_review, db_session: AsyncSession
):
    # Tombstone the series between review-creation and approval.
    series = (
        await db_session.execute(
            select(WordPressSeries).where(
                WordPressSeries.slug == pending_review.wp_series_slug
            )
        )
    ).scalar_one()
    series.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    r = await client.post(
        f"/api/admin/playlist-series-review/{pending_review.id}/approve",
        headers=api_headers(),
        json={"reviewed_by": "Morgan"},
    )
    assert r.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# Reject
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reject_flips_status_without_touching_playlist_tags(
    client: AsyncClient, pending_review, db_session: AsyncSession
):
    r = await client.post(
        f"/api/admin/playlist-series-review/{pending_review.id}/reject",
        headers=api_headers(),
        json={"reviewed_by": "Morgan"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "rejected"

    # No playlist_tags row got created.
    pt = (
        await db_session.execute(
            select(PlaylistTag).where(
                PlaylistTag.youtube_playlist_id == pending_review.youtube_playlist_id
            )
        )
    ).scalar_one_or_none()
    assert pt is None


@pytest.mark.asyncio
async def test_reject_409_if_already_reviewed(
    client: AsyncClient, pending_review
):
    r1 = await client.post(
        f"/api/admin/playlist-series-review/{pending_review.id}/reject",
        headers=api_headers(),
        json={"reviewed_by": "Morgan"},
    )
    assert r1.status_code == 200
    r2 = await client.post(
        f"/api/admin/playlist-series-review/{pending_review.id}/reject",
        headers=api_headers(),
        json={"reviewed_by": "Morgan"},
    )
    assert r2.status_code == 409
