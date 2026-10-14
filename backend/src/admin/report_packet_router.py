"""cht-reports' generate-time data pull. Not the CHT report/generate routes
under /api/admin — those build Content Hub's own HubSpot-based analytics
report, a separate feature for a separate consumer.

Bearer M2M with `hub/reports.{crud}` on its own /api/campaigns prefix
rather than /api/admin.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from admin.deps import verify_reports_access
from database import get_db
from schemas.report_packet import ReportInputPacketOut
from services import report_packet

log = logging.getLogger("contenthub.report_packet")

router = APIRouter(prefix="/api/campaigns", tags=["report-packet"])


def _packet_request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None) or request.headers.get(
        "X-Request-Id"
    )


@router.get(
    "/{campaign_id}/report-packet",
    response_model=ReportInputPacketOut,
)
async def get_report_packet(
    campaign_id: int,
    request: Request,
    _key: Annotated[str, Depends(verify_reports_access)],
    db: Annotated[AsyncSession, Depends(get_db)],
    window_start: date | None = Query(default=None, alias="windowStart"),
    window_end: date | None = Query(default=None, alias="windowEnd"),
    sources: list[str] = Query(default=[]),
) -> ReportInputPacketOut:
    extra = {
        "request_id": _packet_request_id(request),
        "campaign_id": campaign_id,
    }
    try:
        packet = await report_packet.build_report_packet(
            db,
            campaign_id,
            window_start=window_start,
            window_end=window_end,
            sources=sources or None,
        )
        log.info("report-packet ok", extra={**extra, "status_code": 200})
        return packet
    except HTTPException as exc:
        log.warning(
            "report-packet error",
            extra={**extra, "status_code": exc.status_code},
        )
        raise
    except Exception:
        log.exception("report-packet error", extra={**extra, "status_code": 500})
        raise
