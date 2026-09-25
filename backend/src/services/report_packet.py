"""Generate-time input packet for cht-reports (CPR-32).

cht-reports never queries Aurora or cht-platform-tool directly. Generate
time input comes from Content Hub: this module assembles a single
snapshot from whatever Content Hub already has stored, and marks
sources it doesn't have as missing rather than failing the request.

Data sources:
* ``platformSlices`` — ``CampaignPlatformData`` (unchanged)
* ``hubspotRawData`` — ``Campaign.hubspot_raw_data`` (unchanged)
* ``sessions`` — CPR-13 ``export_sessions`` (Zoom) when present for the
  campaign; otherwise shoot ``diarized_transcript`` fallback (Uche:
  Zoom first, shoot fallback only — no union for the same event)
* ``surveyResponses`` — CPR-13 ``export_survey_responses``
* ``template`` — CPR-25 pointer (``type``/``semver``/``s3Key``) to the
  template body in the cht-reports bucket: the campaign's linked template,
  else the latest ``executive_summary`` version

When an export session has ``transcript_s3_key`` but empty
``transcript_text``, and ``PLATFORM_EXPORT_TRANSCRIPT_BUCKET`` is set,
this module may GetObject + strip WebVTT so cht-reports still receives
spoken text (complements CPR-13 ingest / CPR-31). Failures leave text
empty and never 500 the packet.

No live Zoom / platform-tool HTTP from this endpoint.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.campaign import ReportTemplate
from models.export_warehouse import ExportSession, ExportSurveyResponse
from models.shoot import Shoot
from schemas.report_packet import (
    ReportInputPacketOut,
    ReportPacketPlatformSliceOut,
    ReportPacketSessionOut,
    ReportPacketSurveyOut,
    ReportPacketTemplateOut,
    SourceCompletenessOut,
    SourceStatus,
)
from services import campaigns as campaign_service
from services import platform_data
from services.export_ingest.transcript_s3 import (
    S3TranscriptStore,
    TranscriptStore,
    TranscriptStoreError,
)
from services.export_ingest.vtt import strip_vtt

log = logging.getLogger(__name__)

DEFAULT_TEMPLATE_TYPE = "executive_summary"


async def build_report_packet(
    db: AsyncSession,
    campaign_id: int,
    *,
    window_start: date | None = None,
    window_end: date | None = None,
    sources: list[str] | None = None,
    transcript_store: TranscriptStore | None = None,
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

    store = transcript_store if transcript_store is not None else _resolve_transcript_store()
    sessions, sessions_fetched_at = await _load_sessions(
        db, campaign_id, transcript_store=store
    )
    survey_responses, surveys_fetched_at = await _load_surveys(db, campaign_id)

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
        fetched_at=sessions_fetched_at,
        row_count=len(sessions),
        status=SourceStatus.OK if sessions else SourceStatus.MISSING,
    )

    input_completeness["surveyResponses"] = SourceCompletenessOut(
        fetched_at=surveys_fetched_at,
        row_count=len(survey_responses),
        status=SourceStatus.OK if survey_responses else SourceStatus.MISSING,
    )

    template = await _resolve_template(db, campaign.template_id)
    input_completeness["template"] = SourceCompletenessOut(
        fetched_at=template.updated_at if template else None,
        row_count=1 if template else 0,
        status=SourceStatus.OK if template else SourceStatus.MISSING,
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
        survey_responses=survey_responses,
        template=(
            ReportPacketTemplateOut(
                id=template.id,
                type=template.type,
                semver=template.semver,
                s3_key=template.s3_key,
            )
            if template
            else None
        ),
        input_completeness=input_completeness,
    )


async def _resolve_template(
    db: AsyncSession, template_id: int | None
) -> ReportTemplate | None:
    """CPR-25: the campaign's linked template, else the latest Executive Summary.

    Only rows with an S3 body (``s3_key`` + ``semver``) count; older admin
    template rows are catalog entries without a body.
    """
    if template_id is not None:
        linked = await db.get(ReportTemplate, template_id)
        if linked is not None and linked.s3_key and linked.semver:
            return linked

    rows = list(
        (
            await db.execute(
                select(ReportTemplate).where(
                    ReportTemplate.type == DEFAULT_TEMPLATE_TYPE,
                    ReportTemplate.s3_key.is_not(None),
                    ReportTemplate.semver.is_not(None),
                )
            )
        ).scalars()
    )
    return max(rows, key=lambda r: _semver_key(r.semver), default=None)


def _semver_key(semver: str | None) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in (semver or "").split("."))
    except ValueError:
        return (-1,)


def _resolve_transcript_store() -> TranscriptStore | None:
    """Optional S3 store when PLATFORM_EXPORT_TRANSCRIPT_BUCKET is configured."""
    from config import get_settings

    settings = get_settings()
    bucket = (settings.platform_export_transcript_bucket or "").strip()
    if not bucket:
        return None
    return S3TranscriptStore(bucket, region_name=settings.aws_region)


async def _load_sessions(
    db: AsyncSession,
    campaign_id: int,
    *,
    transcript_store: TranscriptStore | None = None,
) -> tuple[list[ReportPacketSessionOut], datetime | None]:
    """Zoom warehouse first; shoot transcripts only if no Zoom rows."""
    export_rows = list(
        (
            await db.execute(
                select(ExportSession)
                .where(ExportSession.campaign_id == campaign_id)
                .order_by(
                    ExportSession.session_date.asc().nulls_last(),
                    ExportSession.id.asc(),
                )
            )
        ).scalars()
    )
    if export_rows:
        sessions = [
            _session_from_export(row, transcript_store=transcript_store)
            for row in export_rows
        ]
        fetched_at = max(
            (row.updated_at for row in export_rows if row.updated_at),
            default=datetime.now(timezone.utc),
        )
        return sessions, fetched_at

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
    fetched_at = datetime.now(timezone.utc) if sessions else None
    return sessions, fetched_at


def _session_from_export(
    row: ExportSession,
    *,
    transcript_store: TranscriptStore | None = None,
) -> ReportPacketSessionOut:
    text = (row.transcript_text or "").strip()
    if not text and row.transcript_s3_key and transcript_store is not None:
        text = _transcript_text_from_store(transcript_store, row.transcript_s3_key)
    return ReportPacketSessionOut(
        platform_tool_program_id=row.platform_tool_program_id,
        kind=row.kind,
        title=row.title,
        session_date=row.session_date,
        zoom_meeting_uuid=row.zoom_uuid,
        transcript_text=text,
    )


def _transcript_text_from_store(store: TranscriptStore, key: str) -> str:
    try:
        return strip_vtt(store.get_vtt(key))
    except TranscriptStoreError as exc:
        log.warning("report-packet transcript GetObject failed key=%s: %s", key, exc)
        return ""


async def _load_surveys(
    db: AsyncSession,
    campaign_id: int,
) -> tuple[list[ReportPacketSurveyOut], datetime | None]:
    rows = list(
        (
            await db.execute(
                select(ExportSurveyResponse)
                .where(ExportSurveyResponse.campaign_id == campaign_id)
                .order_by(
                    ExportSurveyResponse.submitted_at.asc().nulls_last(),
                    ExportSurveyResponse.id.asc(),
                )
            )
        ).scalars()
    )
    if not rows:
        return [], None

    surveys = [
        ReportPacketSurveyOut(
            respondent_id=row.respondent_id,
            source=row.source or "unknown",
            survey_type=row.survey_type,
            submitted_at=row.submitted_at,
            answers=dict(row.answers or {}),
        )
        for row in rows
    ]
    fetched_at = max(
        (row.updated_at for row in rows if row.updated_at),
        default=datetime.now(timezone.utc),
    )
    return surveys, fetched_at
