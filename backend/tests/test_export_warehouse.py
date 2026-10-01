"""Phase B: Zoom export warehouse ORM + SQLite schema smoke tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.campaign import Campaign
from models.export_warehouse import (
    ExportAttendanceEvent,
    ExportIngestRun,
    ExportSession,
    ExportSurveyResponse,
)


@pytest.mark.asyncio
async def test_export_session_round_trip(db_session: AsyncSession):
    campaign = Campaign(name="Warehouse Campaign", program_name="Prog")
    db_session.add(campaign)
    await db_session.flush()

    session = ExportSession(
        platform_tool_program_id="clprog001",
        campaign_id=campaign.id,
        kind="WEBINAR",
        title="Live session",
        session_date=datetime(2026, 8, 15, 17, 0, tzinfo=timezone.utc),
        zoom_meeting_id="81234567890",
        zoom_uuid="AbCdEf==",
        transcript_s3_key="zoom-recordings/clprog001/file.vtt",
        transcript_text=None,
    )
    db_session.add(session)
    await db_session.commit()

    loaded = (
        await db_session.execute(
            select(ExportSession).where(
                ExportSession.platform_tool_program_id == "clprog001"
            )
        )
    ).scalar_one()
    assert loaded.campaign_id == campaign.id
    assert loaded.zoom_meeting_id == "81234567890"
    assert loaded.zoom_uuid == "AbCdEf=="
    assert loaded.zoom_meeting_id != loaded.zoom_uuid
    assert loaded.transcript_text is None


@pytest.mark.asyncio
async def test_export_session_program_id_unique(db_session: AsyncSession):
    db_session.add(ExportSession(platform_tool_program_id="dup"))
    await db_session.commit()

    db_session.add(ExportSession(platform_tool_program_id="dup", title="again"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_attendance_requires_session_and_dedupe_key(db_session: AsyncSession):
    db_session.add(ExportSession(platform_tool_program_id="clprog002"))
    await db_session.flush()

    event = ExportAttendanceEvent(
        dedupe_key="clprog002|WEBHOOK|JOINED|2026-08-15T17:02:11Z|learner@example.com",
        platform_tool_program_id="clprog002",
        source="WEBHOOK",
        event="JOINED",
        occurred_at=datetime(2026, 8, 15, 17, 2, 11, tzinfo=timezone.utc),
        participant_email="learner@example.com",
    )
    db_session.add(event)
    await db_session.commit()

    loaded = (
        await db_session.execute(
            select(ExportAttendanceEvent).where(
                ExportAttendanceEvent.dedupe_key == event.dedupe_key
            )
        )
    ).scalar_one()
    assert loaded.source == "WEBHOOK"
    assert loaded.event == "JOINED"


@pytest.mark.asyncio
async def test_attendance_dedupe_key_unique(db_session: AsyncSession):
    db_session.add(ExportSession(platform_tool_program_id="clprog003"))
    await db_session.flush()

    key = "same-dedupe-key"
    occurred = datetime(2026, 8, 15, 17, 0, tzinfo=timezone.utc)
    db_session.add(
        ExportAttendanceEvent(
            dedupe_key=key,
            platform_tool_program_id="clprog003",
            source="WEBHOOK",
            event="JOINED",
            occurred_at=occurred,
        )
    )
    await db_session.commit()

    db_session.add(
        ExportAttendanceEvent(
            dedupe_key=key,
            platform_tool_program_id="clprog003",
            source="WEBHOOK",
            event="LEFT",
            occurred_at=occurred,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_attendance_fk_requires_session(db_session: AsyncSession):
    # SQLite only enforces FKs when explicitly enabled on the connection.
    await db_session.execute(text("PRAGMA foreign_keys=ON"))
    db_session.add(
        ExportAttendanceEvent(
            dedupe_key="orphan",
            platform_tool_program_id="missing-program",
            source="WEBHOOK",
            event="JOINED",
            occurred_at=datetime(2026, 8, 15, 17, 0, tzinfo=timezone.utc),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_survey_stub_and_ingest_run(db_session: AsyncSession):
    campaign = Campaign(name="Survey Campaign")
    db_session.add(campaign)
    await db_session.flush()

    db_session.add(
        ExportSurveyResponse(
            dedupe_key="sub-1",
            campaign_id=campaign.id,
            submission_id="sub-1",
            source="jotform",
            answers={"q1": "yes"},
        )
    )
    db_session.add(
        ExportIngestRun(
            campaign_id=campaign.id,
            trigger="fixture",
            status="success",
            sessions_upserted=1,
            attendance_upserted=2,
            surveys_upserted=1,
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    surveys = (
        await db_session.execute(select(ExportSurveyResponse))
    ).scalars().all()
    runs = (await db_session.execute(select(ExportIngestRun))).scalars().all()
    assert len(surveys) == 1
    assert surveys[0].answers == {"q1": "yes"}
    assert runs[0].status == "success"
