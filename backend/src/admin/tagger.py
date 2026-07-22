"""Admin tagger observability API (SCRUM-78).

GET /api/admin/tagger/runs?limit=N        → most-recent tagger runs
GET /api/admin/tagger/diffs?limit=N&entity_type=…
                                          → most-recent tag mutations
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from admin.deps import verify_admin_api_key
from database import get_db
from models.tagger_observability import TagDiffRow, TaggerRun
from schemas.admin_tagger import (
    TagDiffList,
    TagDiffOut,
    TaggerRunList,
    TaggerRunOut,
)

router = APIRouter(prefix="/api/admin/tagger", tags=["admin-tagger"])
logger = logging.getLogger("contenthub.admin.tagger")


def _run_to_out(run: TaggerRun) -> TaggerRunOut:
    return TaggerRunOut(
        id=run.id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        mode=run.mode,
        dry_run=run.dry_run,
        shoots_processed=run.shoots_processed,
        shoots_doctors_corrected=run.shoots_doctors_corrected,
        clips_changed=run.clips_changed,
        posts_changed=run.posts_changed,
        clips_curator_locked_skipped=run.clips_curator_locked_skipped,
        posts_curator_locked_skipped=run.posts_curator_locked_skipped,
        orphaned_404_count=run.orphaned_404_count,
        api_error_count=run.api_error_count,
        clip_post_skipped_models_missing=run.clip_post_skipped_models_missing,
    )


def _diff_to_out(d: TagDiffRow) -> TagDiffOut:
    return TagDiffOut(
        id=d.id,
        run_id=d.run_id,
        entity_type=d.entity_type,
        entity_id=d.entity_id,
        shoot_id=d.shoot_id,
        shoot_name=d.shoot_name,
        provider_post_id=d.provider_post_id,
        title=d.title,
        before_tags=list(d.before_tags or []),
        after_tags=list(d.after_tags or []),
        created_at=d.created_at,
    )


@router.get("/runs", response_model=TaggerRunList)
async def list_tagger_runs(
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=25, ge=1, le=100),
) -> TaggerRunList:
    total = (
        await db.execute(select(func.count()).select_from(TaggerRun))
    ).scalar_one()
    rows = list(
        (
            await db.execute(
                select(TaggerRun)
                .order_by(TaggerRun.finished_at.desc())
                .limit(limit)
            )
        ).scalars()
    )
    return TaggerRunList(items=[_run_to_out(r) for r in rows], total=total)


@router.get("/diffs", response_model=TagDiffList)
async def list_tag_diffs(
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=200),
    entity_type: str | None = Query(default=None, pattern="^(shoot|clip|post)$"),
) -> TagDiffList:
    query = select(TagDiffRow)
    count_query = select(func.count()).select_from(TagDiffRow)
    if entity_type:
        query = query.where(TagDiffRow.entity_type == entity_type)
        count_query = select(func.count()).where(
            TagDiffRow.entity_type == entity_type
        )

    total = (await db.execute(count_query)).scalar_one()
    rows = list(
        (
            await db.execute(
                query.order_by(TagDiffRow.created_at.desc()).limit(limit)
            )
        ).scalars()
    )
    return TagDiffList(items=[_diff_to_out(r) for r in rows], total=total)
