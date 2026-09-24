"""Generate-time input packet for cht-reports.

cht-reports never queries Aurora or cht-platform-tool directly. Generate
time input comes from Content Hub: this module assembles a single
snapshot from whatever Content Hub already has stored, and marks
sources it doesn't have as missing rather than failing the request.

Real data today: platformSlices (CampaignPlatformData), hubspotRawData
(Campaign.hubspot_raw_data), sessions (Shoot.diarized_transcript, for
shoots an admin has linked to this campaign via shoots.campaign_id).

surveyResponses ships empty for v1: native SurveyResponse data lives in
cht-platform-tool, not Content Hub, and nothing pulls it cross-repo yet
(CPR-12/13, not built). Marked missing in inputCompleteness, not a 500.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.shoot import Shoot
from schemas.report_packet import (
    ReportInputPacketOut,
    ReportPacketPlatformSliceOut,
    ReportPacketSessionOut,
    SourceCompletenessOut,
    SourceStatus,
)
from services import campaigns as campaign_service
from services import platform_data


async def build_report_packet(
    db: AsyncSession,
    campaign_id: int,
    *,
    window_start: date | None = None,
    window_end: date | None = None,
    sources: list[str] | None = None,
) -> ReportInputPacketOut:
    campaign = await campaign_service._get_campaign_row(db, campaign_id)

    latest_platforms = await platform_data.latest_by_platform(db, campaign_id)
    platform_slices = [
        ReportPacketPlatformSliceOut(
            platform=row.platform,
            fetch_date=row.fetch_date,
            status=row.status,
            row_count=row.row_count,
            rows=row.rows,
            synced_at=row.synced_at,
        )
        for row in latest_platforms.values()
        if row.status == "available"
    ]

    shoots = list(
        (
            await db.execute(
                select(Shoot).where(Shoot.campaign_id == campaign_id)
            )
        ).scalars()
    )
    sessions = [
        ReportPacketSessionOut(
            platform_tool_program_id=None,
            kind=None,
            title=shoot.name,
            session_date=shoot.shoot_date,
            zoom_meeting_uuid=None,
            transcript_text=shoot.diarized_transcript or "",
        )
        for shoot in shoots
        if shoot.diarized_transcript
    ]

    # Dict keys, unlike model fields, aren't touched by ApiModel's
    # camelCase alias generator, so multi-word keys must be written
    # camelCase by hand to match the rest of the wire contract.
    input_completeness: dict[str, SourceCompletenessOut] = {}

    input_completeness["hubspot"] = SourceCompletenessOut(
        fetched_at=campaign.hubspot_synced_at,
        row_count=1 if campaign.hubspot_raw_data else 0,
        status=SourceStatus.OK if campaign.hubspot_raw_data else SourceStatus.MISSING,
    )

    for row in latest_platforms.values():
        input_completeness[row.platform] = SourceCompletenessOut(
            fetched_at=row.synced_at,
            row_count=row.row_count or 0,
            status=SourceStatus.OK if row.status == "available" else SourceStatus.MISSING,
        )

    input_completeness["sessions"] = SourceCompletenessOut(
        fetched_at=datetime.now(timezone.utc) if sessions else None,
        row_count=len(sessions),
        status=SourceStatus.OK if sessions else SourceStatus.MISSING,
    )

    input_completeness["surveyResponses"] = SourceCompletenessOut(
        fetched_at=None,
        row_count=0,
        status=SourceStatus.MISSING,
    )

    return ReportInputPacketOut(
        campaign_id=campaign.id,
        campaign_name=campaign.name,
        window_start=window_start,
        window_end=window_end,
        sources=sources or [],
        hubspot_raw_data=campaign.hubspot_raw_data,
        platform_slices=platform_slices,
        sessions=sessions,
        survey_responses=[],
        input_completeness=input_completeness,
    )
