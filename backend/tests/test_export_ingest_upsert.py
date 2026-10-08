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
    ExportRegistration,
    ExportSession,
    ExportSurveyResponse,
)
from schemas.platform_export import PlatformExportPacket
from services.export_ingest.normalize import (
    normalize_export_payload,
    rewrite_packet_hub_campaign_id,
)
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
    assert surveys[0].jotform_form_id is None


@pytest.mark.asyncio
async def test_ingest_stores_packet_survey_fields(db_session: AsyncSession):
    raw = {
        "campaignId": "AZ-25-01_LIV001",
        "sessions": [],
        "attendance": [],
        "surveys": [
            {
                "platformToolProgramId": "prog-1",
                "type": "POST_TEST",
                "jotformFormId": "jf-99",
                "source": "jotform",
                "responses": [
                    {
                        "userId": "u2",
                        "submittedAt": "2026-09-02T12:00:00Z",
                        "submissionId": "jf-sub-1",
                        "answers": {"q1": "no"},
                    }
                ],
            },
            {
                "platformToolProgramId": "prog-1",
                "type": "FEEDBACK",
                "source": "native",
                "responses": [
                    {
                        "userId": "u3",
                        "submittedAt": "2026-09-02T12:05:00Z",
                        "answers": {"q1": "yes"},
                    }
                ],
            },
        ],
    }
    packet = rewrite_packet_hub_campaign_id(normalize_export_payload(raw), 77)
    await _seed_campaign(db_session, 77)
    await ingest_packet(db_session, packet, trigger="manual")
    await db_session.commit()

    rows = (
        await db_session.execute(
            select(ExportSurveyResponse).order_by(ExportSurveyResponse.submission_id)
        )
    ).scalars().all()
    by_respondent = {row.respondent_id: row for row in rows}
    assert by_respondent["u2"].source == "jotform"
    assert by_respondent["u2"].submission_id == "jf-sub-1"
    assert by_respondent["u2"].jotform_form_id == "jf-99"
    assert by_respondent["u2"].survey_type == "POST_TEST"
    assert by_respondent["u3"].source == "native"
    assert by_respondent["u3"].submission_id is None
    assert by_respondent["u3"].jotform_form_id is None


@pytest.mark.asyncio
async def test_reingest_replaces_legacy_platform_survey_row(
    db_session: AsyncSession,
):
    await _seed_campaign(db_session, 77)
    db_session.add(
        ExportSurveyResponse(
            dedupe_key="submission:survey-native:u3:0",
            campaign_id=77,
            platform_tool_program_id="prog-1",
            respondent_id="u3",
            source="platform",
            survey_type="FEEDBACK",
            submission_id="survey-native:u3:0",
            answers={"q1": "old"},
        )
    )
    await db_session.flush()

    raw = {
        "campaignId": "AZ-25-01_LIV001",
        "sessions": [],
        "attendance": [],
        "surveys": [
            {
                "platformToolProgramId": "prog-1",
                "surveyId": "survey-native",
                "type": "FEEDBACK",
                "source": "native",
                "responses": [
                    {
                        "userId": "u3",
                        "submittedAt": "2026-09-02T12:05:00Z",
                        "answers": {"q1": "yes"},
                    }
                ],
            }
        ],
    }
    packet = rewrite_packet_hub_campaign_id(normalize_export_payload(raw), 77)
    await ingest_packet(db_session, packet, trigger="manual")
    await db_session.commit()

    rows = (
        await db_session.execute(select(ExportSurveyResponse))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].source == "native"
    assert rows[0].dedupe_key != "submission:survey-native:u3:0"
    assert rows[0].answers["q1"] == "yes"


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


@pytest.mark.asyncio
async def test_cpr42_reingest_replaces_stale_attendance_and_registrations(
    db_session: AsyncSession,
):
    """Rolled rows must replace first-wins leftovers so counts don't double."""
    await _seed_campaign(db_session, 7)
    old = PlatformExportPacket.model_validate(
        {
            "campaignId": 7,
            "sessions": [
                {"platformToolProgramId": "prog-1", "title": "Live"},
            ],
            "attendance": [
                {
                    "platformToolProgramId": "prog-1",
                    "source": "WEBHOOK",
                    "event": "JOINED",
                    "occurredAt": "2026-08-15T17:00:00Z",
                    "participantEmail": "a@example.com",
                    "durationSeconds": 30,
                }
            ],
            "registrations": [
                {
                    "platformToolProgramId": "prog-1",
                    "userId": "u-gone",
                    "registeredAt": "2026-08-01T00:00:00Z",
                    "status": "PENDING",
                }
            ],
        }
    )
    await upsert_packet(db_session, old)
    await db_session.commit()

    rolled = PlatformExportPacket.model_validate(
        {
            "campaignId": 7,
            "sessions": [
                {"platformToolProgramId": "prog-1", "title": "Live"},
            ],
            "attendance": [
                {
                    "platformToolProgramId": "prog-1",
                    "source": "REPORT_IMPORT",
                    "event": "JOINED",
                    "joinTime": "2026-08-15T17:00:00Z",
                    "participantEmail": "a@example.com",
                    "durationSeconds": 90,
                    "specialty": "Cardio",
                    "institution": "CHM",
                    "platformEventId": "rollup:prog-1:e:a@example.com",
                    "userId": "u1",
                }
            ],
            "registrations": [
                {
                    "platformToolProgramId": "prog-1",
                    "userId": "u1",
                    "registeredAt": "2026-08-01T00:00:00Z",
                    "status": "APPROVED",
                    "specialty": "Cardio",
                    "institution": "CHM",
                }
            ],
        }
    )
    await upsert_packet(db_session, rolled)
    await db_session.commit()

    attendance = (
        await db_session.execute(select(ExportAttendanceEvent))
    ).scalars().all()
    regs = (
        await db_session.execute(select(ExportRegistration))
    ).scalars().all()
    assert len(attendance) == 1
    assert attendance[0].dedupe_key == (
        "platform_event:rollup:prog-1:e:a@example.com"
    )
    assert attendance[0].duration_seconds == 90
    assert attendance[0].specialty == "Cardio"
    assert len(regs) == 1
    assert regs[0].user_id == "u1"
    assert regs[0].status == "APPROVED"
