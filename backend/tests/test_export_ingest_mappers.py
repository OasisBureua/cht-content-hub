"""Phase C: pure mapper / dedupe-key unit tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from schemas.platform_export import (
    AttendanceEventType,
    AttendanceSource,
    ExportAttendanceEvent,
    ExportSession,
    ExportSurveyResponse,
    PlatformExportPacket,
)
from services.export_ingest.mappers import (
    attendance_dedupe_key,
    map_attendance,
    map_session,
    map_survey,
    survey_dedupe_key,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "platform_export"


def _packet() -> PlatformExportPacket:
    raw = json.loads((FIXTURES / "campaign_42_packet.json").read_text(encoding="utf-8"))
    return PlatformExportPacket.model_validate(raw)


def test_map_session_uses_packet_campaign_fallback():
    session = ExportSession(
        platform_tool_program_id="p1",
        title="T",
        zoom_meeting_id="111",
        zoom_uuid="uuid",
    )
    fields = map_session(session, default_campaign_id=42)
    assert fields["campaign_id"] == 42
    assert fields["zoom_meeting_id"] == "111"
    assert fields["zoom_uuid"] == "uuid"
    assert fields["platform_tool_program_id"] == "p1"


def test_map_session_prefers_explicit_campaign_id():
    session = ExportSession(platform_tool_program_id="p1", campaign_id=7)
    assert map_session(session, default_campaign_id=42)["campaign_id"] == 7


def test_map_session_string_export_id_falls_back_to_hub_default():
    session = ExportSession(
        platform_tool_program_id="p1",
        campaign_id="AZ-25-01_LIV001",
    )
    assert map_session(session, default_campaign_id=42)["campaign_id"] == 42


def test_attendance_dedupe_prefers_platform_event_id():
    event = ExportAttendanceEvent(
        platform_tool_program_id="p1",
        source=AttendanceSource.WEBHOOK,
        event=AttendanceEventType.JOINED,
        occurred_at=datetime(2026, 8, 15, 17, 0, tzinfo=timezone.utc),
        platform_event_id="evt_1",
        participant_email="a@b.com",
    )
    assert attendance_dedupe_key(event) == "platform_event:evt_1"


def test_attendance_dedupe_natural_key_stable():
    event = ExportAttendanceEvent(
        platform_tool_program_id="p1",
        source=AttendanceSource.WEBHOOK,
        event=AttendanceEventType.JOINED,
        occurred_at=datetime(2026, 8, 15, 17, 2, 11, tzinfo=timezone.utc),
        participant_email="Learner@Example.com",
        zoom_participant_id="zp_1",
        join_time=datetime(2026, 8, 15, 17, 2, 11, tzinfo=timezone.utc),
    )
    key = attendance_dedupe_key(event)
    assert key.startswith("p1|WEBHOOK|JOINED|")
    assert "learner@example.com" in key
    assert attendance_dedupe_key(event) == key


def test_survey_dedupe_prefers_submission_id():
    row = ExportSurveyResponse(submission_id="sub_1", source="jotform")
    assert survey_dedupe_key(row) == "submission:sub_1"


def test_fixture_packet_maps_without_error():
    packet = _packet()
    session_fields = map_session(
        packet.sessions[0], default_campaign_id=packet.campaign_id
    )
    assert session_fields["transcript_s3_key"] is not None
    assert session_fields["transcript_text"] is None

    att = map_attendance(packet.attendance[0], default_campaign_id=42)
    assert att["dedupe_key"] == "platform_event:evt_webhook_001"

    survey = map_survey(packet.survey_responses[0], default_campaign_id=42)
    assert survey["dedupe_key"] == "submission:sub_abc123"
    assert survey["answers"]["nps"] == 9
