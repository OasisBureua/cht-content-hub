"""Public /api/public/transcripts/{shoot_id} endpoint — mediahub-parity port.

Returns diarized shoot transcript. Frontend (ClipDetail, PlaylistDetail) splits
`transcript` on newlines into paragraphs and renders `shoot_name` as a caption.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.shoot import Shoot
from public.deps import verify_public_api_key
from public.limits import limiter
from schemas.public import PublicTranscript


router = APIRouter(prefix="/api/public", tags=["public-transcripts"])


@router.get("/transcripts/{shoot_id}", response_model=PublicTranscript)
@limiter.limit("100/minute")
async def get_transcript(
    shoot_id: str,
    request: Request,
    _api_key: Annotated[str, Depends(verify_public_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PublicTranscript:
    """Diarized transcript for a shoot. 404 when shoot is unknown or has no transcript."""
    row = (
        await db.execute(
            select(Shoot.name, Shoot.diarized_transcript).where(Shoot.id == shoot_id)
        )
    ).first()

    if row is None:
        raise HTTPException(status_code=404, detail="Shoot not found")
    if not row.diarized_transcript:
        raise HTTPException(status_code=404, detail="No transcript for this shoot")

    return PublicTranscript(transcript=row.diarized_transcript, shoot_name=row.name)
