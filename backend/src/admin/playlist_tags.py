"""Admin playlist-tag API (SCRUM-74).

GET  /api/admin/playlists/{youtube_playlist_id}/tags   → current tags + lane (404 if no row)
PATCH /api/admin/playlists/{youtube_playlist_id}/tags  → upsert tags/lane

Auth: X-API-Key server-to-server. CHT holds the key and does its own
Studio Cognito JWT + chm-* group check before proxying user requests.

PATCH is upsert semantics: if no `playlist_tags` row exists for the
given `youtube_playlist_id`, one is created with the requested tags/lane
(SCRUM-71 CH-8 population workflow). Otherwise the existing row is
updated in place. Empty PATCH body against a missing row is a no-op
(nothing to persist) and returns the default empty overlay.

Every write runs through services.tag_taxonomy.normalize_and_validate_tags;
malformed tags produce a 422 with per-tag rejection reasons instead of
persisting bad data. Lane is validated against ALLOWED_LANES.

Emits notify_cht_cache_clear(scope='contenthub') on successful writes
so CHT's cached playlist responses drop.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from admin.cache import notify_cht_cache_clear
from admin.deps import verify_admin_api_key
from database import get_db
from models.playlist_tag import PlaylistTag
from schemas.admin_playlist_tags import (
    ALLOWED_LANES,
    PlaylistTagOut,
    PlaylistTagUpdate,
    PlaylistTagValidationError,
)
from services.tag_taxonomy import normalize_and_validate_tags

router = APIRouter(prefix="/api/admin", tags=["admin-playlist-tags"])
logger = logging.getLogger("contenthub.admin.playlist_tags")


def _to_out(row: PlaylistTag) -> PlaylistTagOut:
    return PlaylistTagOut(
        youtube_playlist_id=row.youtube_playlist_id,
        tags=list(row.tags or []),
        lane=row.lane,
    )


async def _get_or_404(db: AsyncSession, playlist_id: str) -> PlaylistTag:
    row = (
        await db.execute(
            select(PlaylistTag).where(PlaylistTag.youtube_playlist_id == playlist_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"No playlist tag row for '{playlist_id}'.",
        )
    return row


@router.get(
    "/playlists/{youtube_playlist_id}/tags",
    response_model=PlaylistTagOut,
    responses={404: {"description": "Playlist has no curator tag row yet."}},
)
async def get_playlist_tags(
    youtube_playlist_id: str,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlaylistTagOut:
    row = await _get_or_404(db, youtube_playlist_id)
    return _to_out(row)


@router.patch(
    "/playlists/{youtube_playlist_id}/tags",
    response_model=PlaylistTagOut,
    responses={
        422: {
            "description": "One or more tags failed taxonomy validation.",
            "model": PlaylistTagValidationError,
        },
    },
)
async def patch_playlist_tags(
    youtube_playlist_id: str,
    payload: PlaylistTagUpdate,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlaylistTagOut:
    """Upsert playlist tags/lane. Creates the row if it doesn't exist."""
    row = (
        await db.execute(
            select(PlaylistTag).where(
                PlaylistTag.youtube_playlist_id == youtube_playlist_id
            )
        )
    ).scalar_one_or_none()

    updates = payload.model_dump(exclude_unset=True)

    # Validate first, before deciding whether to persist. Rejects on either the
    # insert or update path — semantically identical.
    validated_tags: list[str] | None = None
    if "tags" in updates:
        validation = normalize_and_validate_tags(updates["tags"])
        if not validation.ok:
            # Structured 422 — bypass the global handler's message-flatten so the
            # curator UI can render per-tag reasons directly. NestJS-shape envelope
            # (statusCode/message/error) preserved for consistency with the rest
            # of /api/admin/*; `rejected` is the extra payload.
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content={
                    "statusCode": 422,
                    "error": "Unprocessable Entity",
                    "message": "One or more tags failed taxonomy validation.",
                    "rejected": [
                        {"tag": t, "reason": r} for (t, r) in validation.rejected
                    ],
                },
            )
        validated_tags = validation.normalized

    if "lane" in updates:
        new_lane = updates["lane"]
        if new_lane is not None and new_lane not in ALLOWED_LANES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Invalid lane '{new_lane}'. Allowed: "
                    f"{sorted(ALLOWED_LANES)}."
                ),
            )

    if row is None:
        # Row doesn't exist. Empty body against missing row is a no-op — return
        # the default overlay without persisting a phantom empty row.
        if not updates:
            return PlaylistTagOut(
                youtube_playlist_id=youtube_playlist_id, tags=[], lane=None
            )
        row = PlaylistTag(
            youtube_playlist_id=youtube_playlist_id,
            tags=validated_tags if validated_tags is not None else [],
            lane=updates.get("lane"),
        )
        db.add(row)
        await db.flush()
        await db.refresh(row)
        await notify_cht_cache_clear(scope="contenthub")
        return _to_out(row)

    # Existing row — same in-place update flow as before.
    if not updates:
        return _to_out(row)

    changed = False

    if validated_tags is not None and validated_tags != list(row.tags or []):
        row.tags = validated_tags
        changed = True

    if "lane" in updates and updates["lane"] != row.lane:
        row.lane = updates["lane"]
        changed = True

    if changed:
        await db.flush()
        await db.refresh(row)
        await notify_cht_cache_clear(scope="contenthub")

    return _to_out(row)
