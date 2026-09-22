"""Phase A: platform export DTO contract tests (no DB, no HTTP)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from schemas.platform_export import (
    AttendanceEventType,
    AttendanceSource,
    ExportSession,
    PlatformExportPacket,
    SourceCompletenessStatus,
)
from services.export_ingest import PlatformExportPacket as PacketReexport
from services.export_ingest.client import ExportClient

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "platform_export"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_full_packet_fixture_parses():
    packet = PlatformExportPacket.model_validate(_load("campaign_42_packet.json"))

    assert packet.campaign_id == 42
    assert len(packet.sessions) == 1
    assert len(packet.attendance) == 3
    assert len(packet.survey_responses) == 1

    session = packet.sessions[0]
    assert session.platform_tool_program_id == "clxyz001programcuid0001"
    assert session.zoom_meeting_id == "81234567890"
    assert session.zoom_uuid == "AbCdEf=="
    assert session.transcript_s3_key is not None
    assert session.transcript_text is None

    sources = {row.source for row in packet.attendance}
    assert sources == {
        AttendanceSource.WEBHOOK,
        AttendanceSource.REPORT_IMPORT,
    }
    assert packet.attendance[0].event == AttendanceEventType.JOINED
    assert packet.input_completeness["sessions"].status == SourceCompletenessStatus.OK
    assert (
        packet.input_completeness["surveyResponses"].status
        == SourceCompletenessStatus.OK
    )


def test_empty_packet_fixture_parses():
    packet = PlatformExportPacket.model_validate(_load("empty_packet.json"))
    assert packet.campaign_id == 7
    assert packet.sessions == []
    assert packet.attendance == []
    assert packet.input_completeness["sessions"].status == SourceCompletenessStatus.MISSING


def test_session_accepts_snake_case_and_camel_case():
    from_snake = ExportSession.model_validate(
        {
            "platform_tool_program_id": "prog_snake",
            "zoom_meeting_id": "111",
            "zoom_uuid": "uuid-1",
        }
    )
    from_camel = ExportSession.model_validate(
        {
            "platformToolProgramId": "prog_camel",
            "zoomMeetingId": "222",
            "zoomUuid": "uuid-2",
        }
    )
    assert from_snake.platform_tool_program_id == "prog_snake"
    assert from_camel.zoom_meeting_id == "222"


def test_session_requires_platform_tool_program_id():
    with pytest.raises(ValidationError):
        ExportSession.model_validate({"title": "Missing program id"})


def test_attendance_rejects_unknown_source():
    with pytest.raises(ValidationError):
        PlatformExportPacket.model_validate(
            {
                "campaignId": 1,
                "attendance": [
                    {
                        "platformToolProgramId": "p1",
                        "source": "NOT_A_SOURCE",
                        "event": "JOINED",
                        "occurredAt": "2026-08-15T17:00:00Z",
                    }
                ],
            }
        )


def test_packet_round_trip_preserves_zoom_id_split():
    """Meeting id and uuid must stay distinct through dump/load."""
    packet = PlatformExportPacket.model_validate(_load("campaign_42_packet.json"))
    dumped = packet.model_dump(by_alias=True)
    again = PlatformExportPacket.model_validate(dumped)
    session = again.sessions[0]
    assert session.zoom_meeting_id == "81234567890"
    assert session.zoom_uuid == "AbCdEf=="
    assert session.zoom_meeting_id != session.zoom_uuid


def test_export_ingest_reexports_packet_type():
    assert PacketReexport is PlatformExportPacket


def test_export_client_protocol_is_structural():
    class _FixtureClient:
        async def fetch_campaign_packet(self, campaign_id: int) -> PlatformExportPacket:
            return PlatformExportPacket(campaign_id=campaign_id)

    client: ExportClient = _FixtureClient()
    assert client is not None
