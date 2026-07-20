"""Admin playlist-tag API (SCRUM-74).

GET  /api/admin/playlists/{youtube_playlist_id}/tags   → current tags + lane
PATCH /api/admin/playlists/{youtube_playlist_id}/tags  → update tags/lane

Auth: X-API-Key server-to-server. CHT holds the key and does its own
Studio Cognito JWT + chm-* group check before proxying user requests.

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
        404: {"description": "Playlist has no curator tag row yet."},
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
    row = await _get_or_404(db, youtube_playlist_id)

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return _to_out(row)

    changed = False

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
        if validation.normalized != list(row.tags or []):
            row.tags = validation.normalized
            changed = True

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
        if new_lane != row.lane:
            row.lane = new_lane
            changed = True

    if changed:
        await db.flush()
        await db.refresh(row)
        await notify_cht_cache_clear(scope="contenthub")

    return _to_out(row)
