"""Admin KOL API (SCRUM-58).

- SCRUM-60: GET/PATCH admin KOL surface
- SCRUM-62: POST /refresh to enqueue a single-NPI intel poll on SQS
- SCRUM-63: Presigned KOL headshot PUT (direct browser → S3)
- SCRUM-64: Cache-clear notification on every write / refresh completion

Auth: existing X-API-Key server-to-server (`verify_admin_api_key`). CHT holds
the API key and does its own Studio Cognito JWT + chm-* group check before
proxying user requests here.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Annotated

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from admin.cache import notify_cht_cache_clear
from admin.deps import verify_admin_api_key
from config import Settings, get_settings
from database import get_db
from models.kol import KOL
from schemas.admin_kols import (
    KOLAdminListOut,
    KOLAdminOut,
    KOLAdminUpdate,
    KOLHeadshotPresignOut,
    KOLHeadshotPresignRequest,
    KOLRefreshOut,
)
from services import kol_queries, kol_write

router = APIRouter(prefix="/api/admin", tags=["admin-kols"])
logger = logging.getLogger("contenthub.admin.kols")


# In-process cooldown map for POST /refresh. Keyed by slug, value is unix ts
# of the most recent enqueue. Ephemeral by design — a per-container cooldown
# is acceptable spam-mitigation for admin-only traffic.
_REFRESH_COOLDOWN: dict[str, float] = {}


def _to_admin_out(kol: KOL) -> KOLAdminOut:
    return KOLAdminOut(
        id=kol.id,
        slug=kol.slug,
        name=kol.name,
        title=kol.title,
        specialty=kol.specialty,
        institution=kol.institution,
        bio=kol.bio,
        photo_url=kol.photo_url,
        region=kol.region,
        region_label=kol.region_label,
        display_order=kol.display_order,
        featured=kol.featured,
        curated_fields=list(kol.curated_fields or []),
        hcp_npi=kol.hcp_npi,
        hcp_match_status=kol.hcp_match_status,
        created_at=kol.created_at,
        updated_at=kol.updated_at,
    )


# ---------------------------------------------------------------------------
# SCRUM-60: GET list + GET detail + PATCH detail
# ---------------------------------------------------------------------------


@router.get("/kols", response_model=KOLAdminListOut)
async def list_admin_kols(
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str | None = Query(default=None, description="Case-insensitive name/slug search"),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> KOLAdminListOut:
    query = select(KOL)
    if q:
        term = f"%{q}%"
        query = query.where((KOL.name.ilike(term)) | (KOL.slug.ilike(term)))

    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar_one()

    query = query.order_by(
        KOL.featured.desc(),
        KOL.display_order.asc().nulls_last(),
        KOL.name.asc(),
    ).limit(limit).offset(offset)

    rows = list((await db.execute(query)).scalars())
    return KOLAdminListOut(items=[_to_admin_out(k) for k in rows], total=total)


@router.get("/kols/{slug}", response_model=KOLAdminOut)
async def get_admin_kol(
    slug: str,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KOLAdminOut:
    kol, _resolved = await kol_queries.get_kol_by_slug(db, slug)
    return _to_admin_out(kol)


@router.patch(
    "/kols/{slug}",
    response_model=KOLAdminOut,
    responses={
        404: {"description": "No KOL with that slug."},
    },
)
async def patch_admin_kol(
    slug: str,
    payload: KOLAdminUpdate,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KOLAdminOut:
    kol, _resolved = await kol_queries.get_kol_by_slug(db, slug)

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return _to_admin_out(kol)

    changed = kol_write.apply_kol_field_update(kol, updates, source="admin")
    await db.flush()
    await db.refresh(kol)

    if changed:
        # SCRUM-64: bust CHT's contenthub-namespaced cache. Fire-and-forget —
        # if it fails, admin write is still committed; next TTL cycle recovers.
        await notify_cht_cache_clear(scope="contenthub")

    return _to_admin_out(kol)


# ---------------------------------------------------------------------------
# SCRUM-62: POST /refresh — enqueue single-NPI intel poll
# ---------------------------------------------------------------------------


@router.post(
    "/kols/{slug}/refresh",
    response_model=KOLRefreshOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        404: {"description": "No KOL with that slug."},
        502: {"description": "SQS send_message failed — infrastructure issue, retry later."},
    },
)
async def refresh_admin_kol(
    slug: str,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KOLRefreshOut:
    kol, _resolved = await kol_queries.get_kol_by_slug(db, slug)

    if not kol.hcp_npi:
        return KOLRefreshOut(
            status="no_op",
            reason="KOL is not matched to an HCP NPI — nothing to refresh.",
            slug=kol.slug,
            hcp_npi=None,
        )

    now = time.time()
    last = _REFRESH_COOLDOWN.get(kol.slug, 0.0)
    remaining = int(settings.kol_refresh_cooldown_seconds - (now - last))
    if remaining > 0:
        return KOLRefreshOut(
            status="cooldown",
            reason=f"Cooldown active — retry in {remaining}s.",
            slug=kol.slug,
            hcp_npi=kol.hcp_npi,
            cooldown_remaining_seconds=remaining,
        )

    queue_url = settings.hcp_intel_poll_queue_url
    if not queue_url:
        # Local dev / tests: SQS not wired. Report the no-op but still trip
        # the cooldown so behaviour matches prod for test-driven refresh spam.
        _REFRESH_COOLDOWN[kol.slug] = now
        return KOLRefreshOut(
            status="no_op",
            reason="HCP_INTEL_POLL_QUEUE_URL not configured — refresh skipped.",
            slug=kol.slug,
            hcp_npi=kol.hcp_npi,
        )

    try:
        sqs = boto3.client("sqs", region_name=settings.aws_region)
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(
                {
                    "source": "admin_kol_refresh",
                    "npi": kol.hcp_npi,
                    "slug": kol.slug,
                    "enqueued_at": now,
                }
            ),
        )
    except (BotoCoreError, ClientError) as exc:
        logger.warning(
            "hcp_intel_poll enqueue failed",
            extra={"slug": kol.slug, "npi": kol.hcp_npi, "error": str(exc)},
        )
        raise HTTPException(
            status_code=502,
            detail="Failed to enqueue intel-poll refresh — try again later.",
        )

    _REFRESH_COOLDOWN[kol.slug] = now

    # SCRUM-64: intel refresh will eventually update HCP data; bust cache so
    # frontend picks up the enqueue-in-flight state and re-reads on next TTL.
    await notify_cht_cache_clear(scope="contenthub")

    return KOLRefreshOut(status="enqueued", slug=kol.slug, hcp_npi=kol.hcp_npi)


# ---------------------------------------------------------------------------
# SCRUM-63: presigned KOL headshot upload
# ---------------------------------------------------------------------------


_HEADSHOT_EXT: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
_PRESIGN_EXPIRY_SECONDS = 300  # 5 minutes — matches typical browser upload flow


@router.post(
    "/kols/{slug}/headshot/presign",
    response_model=KOLHeadshotPresignOut,
    responses={
        400: {"description": "Unsupported content_type (must be image/jpeg, image/png, or image/webp)."},
        404: {"description": "No KOL with that slug."},
        502: {"description": "S3 presign generation failed — retry later."},
        503: {"description": "ASSETS_BUCKET not configured on this environment."},
    },
)
async def presign_kol_headshot(
    slug: str,
    payload: KOLHeadshotPresignRequest,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KOLHeadshotPresignOut:
    kol, _resolved = await kol_queries.get_kol_by_slug(db, slug)

    ext = _HEADSHOT_EXT.get(payload.content_type)
    if ext is None:
        raise HTTPException(
            status_code=400,
            detail="Unsupported content_type — use image/jpeg, image/png, or image/webp.",
        )

    bucket = settings.assets_bucket
    if not bucket:
        raise HTTPException(
            status_code=503,
            detail="ASSETS_BUCKET not configured — headshot uploads unavailable.",
        )

    key = f"kol-headshots/{kol.slug}.{ext}"
    photo_url = (
        f"https://{bucket}.s3.{settings.aws_region}.amazonaws.com/{key}"
    )

    try:
        s3 = boto3.client("s3", region_name=settings.aws_region)
        upload_url = s3.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": bucket,
                "Key": key,
                "ContentType": payload.content_type,
            },
            ExpiresIn=_PRESIGN_EXPIRY_SECONDS,
        )
    except (BotoCoreError, ClientError) as exc:
        logger.warning(
            "presign generation failed",
            extra={"slug": kol.slug, "error": str(exc)},
        )
        raise HTTPException(
            status_code=502,
            detail="Failed to generate presigned URL — try again later.",
        )

    return KOLHeadshotPresignOut(
        upload_url=upload_url,
        upload_headers={"Content-Type": payload.content_type},
        key=key,
        photo_url=photo_url,
        expires_in_seconds=_PRESIGN_EXPIRY_SECONDS,
    )
