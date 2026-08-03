"""Admin API for playlist ↔ series match review queue (WPR-6).

Endpoints:
- GET  /api/admin/playlist-series-review               — list rows, filter by status
- POST /api/admin/playlist-series-review               — manually insert a candidate
- POST /api/admin/playlist-series-review/{id}/approve  — approve + write playlist_tags
- POST /api/admin/playlist-series-review/{id}/reject   — reject (audit trail)

Auth: X-API-Key server-to-server. Same auth model as other admin endpoints.

On approval:
- Sets review row status='approved', reviewed_at=now, reviewed_by=<supplied>.
- Sets playlist_tags.wp_series_slug = wp_series_slug. Creates the
  playlist_tags row if it doesn't exist (upsert).
- Fires cache-clear so CHT picks up the new link.

Approval is atomic — the review update + playlist_tags upsert happen in
one transaction. A failure on either side rolls back both.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from admin.cache import notify_cht_cache_clear
from admin.deps import verify_admin_api_key
from database import get_db
from models.playlist_series_match_review import PlaylistSeriesMatchReview
from models.playlist_tag import PlaylistTag
from models.wordpress_projection import WordPressSeries
from schemas.admin_playlist_series_review import (
    PlaylistSeriesReviewCreate,
    PlaylistSeriesReviewDecision,
    PlaylistSeriesReviewList,
    PlaylistSeriesReviewOut,
)

router = APIRouter(prefix="/api/admin", tags=["admin-playlist-series-review"])
logger = logging.getLogger("contenthub.admin.playlist_series_review")

_VALID_STATUSES = frozenset({"pending", "approved", "rejected"})


def _to_out(row: PlaylistSeriesMatchReview) -> PlaylistSeriesReviewOut:
    return PlaylistSeriesReviewOut(
        id=row.id,
        youtube_playlist_id=row.youtube_playlist_id,
        wp_series_slug=row.wp_series_slug,
        match_score=row.match_score,
        signals=row.signals or {},
        status=row.status,
        created_at=row.created_at,
        reviewed_at=row.reviewed_at,
        reviewed_by=row.reviewed_by,
    )


@router.get(
    "/playlist-series-review",
    response_model=PlaylistSeriesReviewList,
    dependencies=[Depends(verify_admin_api_key)],
)
async def list_reviews(
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: str = Query(
        "pending",
        alias="status",
        description="Filter by status: pending | approved | rejected | all",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> PlaylistSeriesReviewList:
    """List review-queue rows. Default: oldest pending first (FIFO)."""
    if status_filter != "all" and status_filter not in _VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"invalid status: {status_filter!r}",
        )

    stmt = select(PlaylistSeriesMatchReview)
    if status_filter != "all":
        stmt = stmt.where(PlaylistSeriesMatchReview.status == status_filter)

    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()

    stmt = stmt.order_by(PlaylistSeriesMatchReview.created_at.asc()).limit(limit).offset(offset)
    rows = list((await db.execute(stmt)).scalars())

    return PlaylistSeriesReviewList(
        items=[_to_out(r) for r in rows], total=total
    )


@router.post(
    "/playlist-series-review",
    response_model=PlaylistSeriesReviewOut,
    dependencies=[Depends(verify_admin_api_key)],
    status_code=status.HTTP_201_CREATED,
)
async def create_review(
    body: PlaylistSeriesReviewCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlaylistSeriesReviewOut:
    """Insert a candidate review row. Fuzzy-match Lambda uses this shape too.

    Rejects if the referenced series doesn't exist (or is tombstoned) — a
    review row against a nonexistent target isn't actionable.
    """
    series_exists = (
        await db.execute(
            select(WordPressSeries.slug)
            .where(WordPressSeries.slug == body.wp_series_slug)
            .where(WordPressSeries.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if series_exists is None:
        raise HTTPException(
            status_code=422,
            detail=f"series not found or tombstoned: {body.wp_series_slug!r}",
        )

    # Reject duplicate pending rows for the same pair (upstream Lambda
    # SHOULD dedupe but we defend at API boundary too).
    existing = (
        await db.execute(
            select(PlaylistSeriesMatchReview)
            .where(
                PlaylistSeriesMatchReview.youtube_playlist_id
                == body.youtube_playlist_id
            )
            .where(
                PlaylistSeriesMatchReview.wp_series_slug == body.wp_series_slug
            )
            .where(PlaylistSeriesMatchReview.status == "pending")
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="pending review already exists for this pair",
        )

    row = PlaylistSeriesMatchReview(
        youtube_playlist_id=body.youtube_playlist_id,
        wp_series_slug=body.wp_series_slug,
        match_score=body.match_score,
        signals=body.signals,
        status="pending",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_out(row)


async def _fetch_pending_review(
    db: AsyncSession, review_id: int
) -> PlaylistSeriesMatchReview:
    row = (
        await db.execute(
            select(PlaylistSeriesMatchReview).where(
                PlaylistSeriesMatchReview.id == review_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"review not found: {review_id}"
        )
    if row.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"review already {row.status}",
        )
    return row


@router.post(
    "/playlist-series-review/{review_id}/approve",
    response_model=PlaylistSeriesReviewOut,
    dependencies=[Depends(verify_admin_api_key)],
)
async def approve_review(
    review_id: int,
    body: PlaylistSeriesReviewDecision,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlaylistSeriesReviewOut:
    """Approve a review row + link the playlist to the series.

    Atomic: review row status change + playlist_tags upsert happen in one
    transaction. If the series has been tombstoned since the review row
    was created, we reject with 422 (no useful link possible).
    """
    row = await _fetch_pending_review(db, review_id)

    series_live = (
        await db.execute(
            select(WordPressSeries.slug)
            .where(WordPressSeries.slug == row.wp_series_slug)
            .where(WordPressSeries.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if series_live is None:
        raise HTTPException(
            status_code=422,
            detail=f"series no longer exists: {row.wp_series_slug!r}",
        )

    # Upsert playlist_tags with wp_series_slug link.
    pt = (
        await db.execute(
            select(PlaylistTag).where(
                PlaylistTag.youtube_playlist_id == row.youtube_playlist_id
            )
        )
    ).scalar_one_or_none()
    if pt is None:
        pt = PlaylistTag(
            youtube_playlist_id=row.youtube_playlist_id,
            tags=[],
            lane=None,
            wp_series_slug=row.wp_series_slug,
        )
        db.add(pt)
    else:
        pt.wp_series_slug = row.wp_series_slug

    now = datetime.now(timezone.utc)
    row.status = "approved"
    row.reviewed_at = now
    row.reviewed_by = body.reviewed_by

    await db.commit()
    await db.refresh(row)

    await notify_cht_cache_clear(scope="contenthub")

    return _to_out(row)


@router.post(
    "/playlist-series-review/{review_id}/reject",
    response_model=PlaylistSeriesReviewOut,
    dependencies=[Depends(verify_admin_api_key)],
)
async def reject_review(
    review_id: int,
    body: PlaylistSeriesReviewDecision,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlaylistSeriesReviewOut:
    """Reject a review row. Row stays as an audit trail so the fuzzy-match
    Lambda doesn't re-suggest this pair."""
    row = await _fetch_pending_review(db, review_id)

    now = datetime.now(timezone.utc)
    row.status = "rejected"
    row.reviewed_at = now
    row.reviewed_by = body.reviewed_by

    await db.commit()
    await db.refresh(row)
    return _to_out(row)
