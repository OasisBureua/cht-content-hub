"""cht-reports' generate-time data pull. Not the CHT report/generate routes
under /api/admin — those build Content Hub's own HubSpot-based analytics
report, a separate feature for a separate consumer.

Bearer M2M with `hub/reports.{crud}` on its own /api/campaigns prefix
rather than /api/admin.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from admin.deps import verify_reports_access
from database import get_db
from schemas.report_packet import ReportInputPacketOut
from services import report_packet

router = APIRouter(prefix="/api/campaigns", tags=["report-packet"])


@router.get(
    "/{campaign_id}/report-packet",
    response_model=ReportInputPacketOut,
)
async def get_report_packet(
    campaign_id: int,
    _key: Annotated[str, Depends(verify_reports_access)],
    db: Annotated[AsyncSession, Depends(get_db)],
    window_start: date | None = Query(default=None, alias="windowStart"),
    window_end: date | None = Query(default=None, alias="windowEnd"),
    sources: list[str] = Query(default=[]),
) -> ReportInputPacketOut:
    return await report_packet.build_report_packet(
        db,
        campaign_id,
        window_start=window_start,
        window_end=window_end,
        sources=sources or None,
    )
