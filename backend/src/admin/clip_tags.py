"""Admin clip-tag override API (SCRUM-75).

PATCH /api/admin/clips/{id}/tags — curator sets tags directly, auto-locks
the row against the playlist_doctor_tagger's daily overwrite.

The tagger checks clip.tags_curator_override in its Clip loop; when True,
it skips the row entirely (see jobs/playlist_doctor_tagger_core.py).

Any tag write implicitly sets tags_curator_override = True so the curator
doesn't have to remember the flag. Setting it False explicitly re-opens
the row to the daily tagger.

Every write runs tags through services.tag_taxonomy.normalize_and_validate_tags.
Rejected tags produce a structured 422 (same shape as SCRUM-74) with per-tag
reasons.
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
from models.clip import Clip
from schemas.admin_clip_tags import ClipTagsOut, ClipTagsUpdate
from services.tag_taxonomy import normalize_and_validate_tags

router = APIRouter(prefix="/api/admin", tags=["admin-clip-tags"])
logger = logging.getLogger("contenthub.admin.clip_tags")


def _to_out(clip: Clip) -> ClipTagsOut:
    return ClipTagsOut(
        id=clip.id,
        tags=list(clip.tags or []),
        tags_curator_override=bool(clip.tags_curator_override),
    )


async def _get_or_404(db: AsyncSession, clip_id: str) -> Clip:
    clip = (
        await db.execute(select(Clip).where(Clip.id == clip_id))
    ).scalar_one_or_none()
    if clip is None:
        raise HTTPException(status_code=404, detail=f"No clip with id '{clip_id}'.")
    return clip


@router.get(
    "/clips/{clip_id}/tags",
    response_model=ClipTagsOut,
    responses={404: {"description": "No clip with that id."}},
)
async def get_clip_tags(
    clip_id: str,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClipTagsOut:
    clip = await _get_or_404(db, clip_id)
    return _to_out(clip)


@router.patch(
    "/clips/{clip_id}/tags",
    response_model=ClipTagsOut,
    responses={
        404: {"description": "No clip with that id."},
        422: {"description": "One or more tags failed taxonomy validation."},
    },
)
async def patch_clip_tags(
    clip_id: str,
    payload: ClipTagsUpdate,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClipTagsOut | JSONResponse:
    clip = await _get_or_404(db, clip_id)

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return _to_out(clip)

    changed = False

    if "tags" in updates:
        validation = normalize_and_validate_tags(updates["tags"])
        if not validation.ok:
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
        if validation.normalized != list(clip.tags or []):
            clip.tags = validation.normalized
            changed = True
        # SCRUM-75: any curator tag write auto-locks against the tagger.
        if not clip.tags_curator_override:
            clip.tags_curator_override = True
            changed = True

    if "tags_curator_override" in updates:
        new_val = bool(updates["tags_curator_override"])
        if new_val != clip.tags_curator_override:
            clip.tags_curator_override = new_val
            changed = True

    if changed:
        await db.flush()
        await db.refresh(clip)
        await notify_cht_cache_clear(scope="contenthub")

    return _to_out(clip)
