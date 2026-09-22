"""Idempotent warehouse upserts for platform export packets.

Sessions first (attendance FK), then attendance, then surveys. Creates a
minimal session stub when attendance references a program absent from the
packet so raw events are not dropped.

When a ``TranscriptStore`` is provided, sessions with ``transcript_s3_key``
and empty ``transcript_text`` are filled by GetObject + VTT cue stripping.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.export_warehouse import (
    ExportAttendanceEvent,
    ExportIngestRun,
    ExportSession,
    ExportSurveyResponse,
)
from schemas.platform_export import (
    ExportSession as ExportSessionDTO,
    PlatformExportPacket,
)
from services.export_ingest.mappers import map_attendance, map_session, map_survey
from services.export_ingest.transcript_s3 import TranscriptStore
from services.export_ingest.vtt import strip_vtt


@dataclass(frozen=True)
class IngestCounts:
    sessions_upserted: int
    attendance_upserted: int
    surveys_upserted: int


def _apply_fields(row: object, fields: dict) -> None:
    for key, value in fields.items():
        setattr(row, key, value)


def enrich_session_transcript(
    session: ExportSessionDTO,
    store: TranscriptStore,
) -> ExportSessionDTO:
    """Fill ``transcript_text`` from S3 VTT when missing."""
    if session.transcript_text:
        return session
    if not session.transcript_s3_key:
        return session
    raw = store.get_vtt(session.transcript_s3_key)
    return session.model_copy(update={"transcript_text": strip_vtt(raw)})


async def _upsert_session(
    db: AsyncSession,
    fields: dict,
) -> ExportSession:
    program_id = fields["platform_tool_program_id"]
    existing = (
        await db.execute(
            select(ExportSession).where(
                ExportSession.platform_tool_program_id == program_id
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        row = ExportSession(**fields)
        db.add(row)
        await db.flush()
        return row
    _apply_fields(existing, fields)
    await db.flush()
    return existing


async def _ensure_session_stub(
    db: AsyncSession,
    *,
    platform_tool_program_id: str,
    campaign_id: int | None,
) -> None:
    existing = (
        await db.execute(
            select(ExportSession.id).where(
                ExportSession.platform_tool_program_id == platform_tool_program_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    db.add(
        ExportSession(
            platform_tool_program_id=platform_tool_program_id,
            campaign_id=campaign_id,
        )
    )
    await db.flush()


async def _upsert_attendance(db: AsyncSession, fields: dict) -> ExportAttendanceEvent:
    existing = (
        await db.execute(
            select(ExportAttendanceEvent).where(
                ExportAttendanceEvent.dedupe_key == fields["dedupe_key"]
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        row = ExportAttendanceEvent(**fields)
        db.add(row)
        await db.flush()
        return row
    _apply_fields(existing, fields)
    await db.flush()
    return existing


async def _upsert_survey(db: AsyncSession, fields: dict) -> ExportSurveyResponse:
    existing = (
        await db.execute(
            select(ExportSurveyResponse).where(
                ExportSurveyResponse.dedupe_key == fields["dedupe_key"]
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        row = ExportSurveyResponse(**fields)
        db.add(row)
        await db.flush()
        return row
    _apply_fields(existing, fields)
    await db.flush()
    return existing


async def upsert_packet(
    db: AsyncSession,
    packet: PlatformExportPacket,
    *,
    transcript_store: TranscriptStore | None = None,
) -> IngestCounts:
    """Upsert all packet rows. Does not write an ingest-run audit row."""
    campaign_id = packet.campaign_id

    for session in packet.sessions:
        if transcript_store is not None:
            session = enrich_session_transcript(session, transcript_store)
        await _upsert_session(
            db, map_session(session, default_campaign_id=campaign_id)
        )

    for event in packet.attendance:
        await _ensure_session_stub(
            db,
            platform_tool_program_id=event.platform_tool_program_id,
            campaign_id=campaign_id,
        )
        await _upsert_attendance(
            db, map_attendance(event, default_campaign_id=campaign_id)
        )

    for survey in packet.survey_responses:
        await _upsert_survey(
            db, map_survey(survey, default_campaign_id=campaign_id)
        )

    return IngestCounts(
        sessions_upserted=len(packet.sessions),
        attendance_upserted=len(packet.attendance),
        surveys_upserted=len(packet.survey_responses),
    )


async def ingest_packet(
    db: AsyncSession,
    packet: PlatformExportPacket,
    *,
    trigger: str = "fixture",
    transcript_store: TranscriptStore | None = None,
) -> ExportIngestRun:
    """Upsert packet contents and record an ``export_ingest_runs`` audit row."""
    started = datetime.now(timezone.utc)
    run = ExportIngestRun(
        campaign_id=packet.campaign_id,
        trigger=trigger,
        status="running",
        started_at=started,
    )
    db.add(run)
    await db.flush()

    try:
        counts = await upsert_packet(
            db, packet, transcript_store=transcript_store
        )
    except Exception as exc:  # noqa: BLE001 — persist failure on the audit row
        run.status = "error"
        run.error = str(exc)
        run.finished_at = datetime.now(timezone.utc)
        await db.flush()
        raise

    run.status = "success"
    run.sessions_upserted = counts.sessions_upserted
    run.attendance_upserted = counts.attendance_upserted
    run.surveys_upserted = counts.surveys_upserted
    run.finished_at = datetime.now(timezone.utc)
    await db.flush()
    return run
