"""Phase C: idempotent warehouse upsert from export fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.campaign import Campaign
from models.export_warehouse import (
    ExportAttendanceEvent,
    ExportIngestRun,
    ExportSession,
    ExportSurveyResponse,
)
from schemas.platform_export import PlatformExportPacket
from services.export_ingest.upsert import ingest_packet, upsert_packet

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "platform_export"


def _load_packet(name: str = "campaign_42_packet.json") -> PlatformExportPacket:
    raw = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return PlatformExportPacket.model_validate(raw)


async def _seed_campaign(db: AsyncSession, campaign_id: int) -> None:
    """Insert a campaign row with a fixed id matching the fixture."""
    campaign = Campaign(id=campaign_id, name=f"Campaign {campaign_id}")
    db.add(campaign)
    await db.flush()


@pytest.mark.asyncio
async def test_ingest_fixture_packet_persists_rows(db_session: AsyncSession):
    packet = _load_packet()
    await _seed_campaign(db_session, packet.campaign_id)

    run = await ingest_packet(db_session, packet, trigger="fixture")
    await db_session.commit()

    assert run.status == "success"
    assert run.sessions_upserted == 1
    assert run.attendance_upserted == 3
    assert run.surveys_upserted == 1

    sessions = (await db_session.execute(select(ExportSession))).scalars().all()
    attendance = (
        await db_session.execute(select(ExportAttendanceEvent))
    ).scalars().all()
    surveys = (
        await db_session.execute(select(ExportSurveyResponse))
    ).scalars().all()

    assert len(sessions) == 1
    assert sessions[0].platform_tool_program_id == "clxyz001programcuid0001"
    assert sessions[0].zoom_meeting_id == "81234567890"
    assert sessions[0].zoom_uuid == "AbCdEf=="
    assert sessions[0].campaign_id == 42
    assert len(attendance) == 3
    assert len(surveys) == 1
    assert surveys[0].answers["q1"] == "excellent"


@pytest.mark.asyncio
async def test_double_ingest_is_idempotent(db_session: AsyncSession):
    packet = _load_packet()
    await _seed_campaign(db_session, packet.campaign_id)

    await ingest_packet(db_session, packet, trigger="fixture")
    # Mutate title on second pass — should update in place, not insert.
    packet.sessions[0].title = "Updated title"
    packet.attendance[0].participant_name = "Updated Name"
    await ingest_packet(db_session, packet, trigger="fixture")
    await db_session.commit()

    session_count = (
        await db_session.execute(select(func.count()).select_from(ExportSession))
    ).scalar_one()
    attendance_count = (
        await db_session.execute(
            select(func.count()).select_from(ExportAttendanceEvent)
        )
    ).scalar_one()
    survey_count = (
        await db_session.execute(
            select(func.count()).select_from(ExportSurveyResponse)
        )
    ).scalar_one()
    run_count = (
        await db_session.execute(select(func.count()).select_from(ExportIngestRun))
    ).scalar_one()

    assert session_count == 1
    assert attendance_count == 3
    assert survey_count == 1
    assert run_count == 2

    session = (await db_session.execute(select(ExportSession))).scalar_one()
    assert session.title == "Updated title"
    joined = (
        await db_session.execute(
            select(ExportAttendanceEvent).where(
                ExportAttendanceEvent.dedupe_key == "platform_event:evt_webhook_001"
            )
        )
    ).scalar_one()
    assert joined.participant_name == "Updated Name"


@pytest.mark.asyncio
async def test_attendance_without_session_creates_stub(db_session: AsyncSession):
    packet = PlatformExportPacket.model_validate(
        {
            "campaignId": 9,
            "sessions": [],
            "attendance": [
                {
                    "platformToolProgramId": "orphan_prog",
                    "source": "WEBHOOK",
                    "event": "JOINED",
                    "occurredAt": "2026-08-15T17:00:00Z",
                    "platformEventId": "evt_orphan",
                }
            ],
        }
    )
    await _seed_campaign(db_session, 9)
    counts = await upsert_packet(db_session, packet)
    await db_session.commit()

    assert counts.attendance_upserted == 1
    session = (
        await db_session.execute(
            select(ExportSession).where(
                ExportSession.platform_tool_program_id == "orphan_prog"
            )
        )
    ).scalar_one()
    assert session.campaign_id == 9
    assert session.title is None


@pytest.mark.asyncio
async def test_empty_packet_ingest(db_session: AsyncSession):
    packet = _load_packet("empty_packet.json")
    await _seed_campaign(db_session, packet.campaign_id)
    run = await ingest_packet(db_session, packet)
    await db_session.commit()
    assert run.status == "success"
    assert run.sessions_upserted == 0
    assert (
        await db_session.execute(select(func.count()).select_from(ExportSession))
    ).scalar_one() == 0
