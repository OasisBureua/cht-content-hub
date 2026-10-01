"""cht-reports' generate-time report-packet endpoint."""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import api_headers
from models.export_warehouse import ExportSession, ExportSurveyResponse
from models.shoot import Shoot
from services.export_ingest.transcript_s3 import MemoryTranscriptStore


def admin_headers(**extra: str) -> dict[str, str]:
    return api_headers(**extra)


@pytest.mark.asyncio
async def test_report_packet_requires_api_key(http_client: AsyncClient):
    response = await http_client.get("/api/campaigns/1/report-packet")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_report_packet_404_for_missing_campaign(client: AsyncClient):
    response = await client.get(
        "/api/campaigns/999999/report-packet",
        headers=admin_headers(),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_report_packet_marks_missing_sources(client: AsyncClient):
    create = await client.post(
        "/api/admin/campaigns",
        headers=admin_headers(),
        json={"name": "Empty Campaign"},
    )
    campaign_id = create.json()["id"]

    response = await client.get(
        f"/api/campaigns/{campaign_id}/report-packet",
        headers=admin_headers(),
    )
    assert response.status_code == 200
    body = response.json()

    assert body["campaignId"] == campaign_id
    assert body["campaignName"] == "Empty Campaign"
    assert body["platformSlices"] == []
    assert body["sessions"] == []
    assert body["surveyResponses"] == []
    assert body["inputCompleteness"]["hubspot"]["status"] == "missing"
    assert body["inputCompleteness"]["sessions"]["status"] == "missing"
    assert body["inputCompleteness"]["surveyResponses"]["status"] == "missing"


@pytest.mark.asyncio
async def test_report_packet_includes_hubspot_data(client: AsyncClient):
    create = await client.post(
        "/api/admin/campaigns",
        headers=admin_headers(),
        json={"name": "HubSpot Campaign"},
    )
    campaign_id = create.json()["id"]

    await client.patch(
        f"/api/admin/campaigns/{campaign_id}",
        headers=admin_headers(),
        json={"hubspotRawData": {"opens": 42}},
    )

    response = await client.get(
        f"/api/campaigns/{campaign_id}/report-packet",
        headers=admin_headers(),
    )
    body = response.json()

    assert body["hubspotRawData"] == {"opens": 42}
    assert body["inputCompleteness"]["hubspot"]["status"] == "ok"


@pytest.mark.asyncio
async def test_report_packet_includes_linked_shoot_transcript(
    client: AsyncClient, db_session: AsyncSession
):
    create = await client.post(
        "/api/admin/campaigns",
        headers=admin_headers(),
        json={"name": "Shoot-Linked Campaign"},
    )
    campaign_id = create.json()["id"]

    shoot = Shoot(
        id="shoot-report-packet-1",
        name="Dr. Smith interview",
        campaign_id=campaign_id,
        shoot_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
        diarized_transcript="Dr. Smith [00:00]:\nHello and welcome.",
    )
    db_session.add(shoot)
    await db_session.commit()

    response = await client.get(
        f"/api/campaigns/{campaign_id}/report-packet",
        headers=admin_headers(),
    )
    body = response.json()

    assert len(body["sessions"]) == 1
    assert body["sessions"][0]["title"] == "Dr. Smith interview"
    assert body["sessions"][0]["transcriptText"] == "Dr. Smith [00:00]:\nHello and welcome."
    assert body["inputCompleteness"]["sessions"]["status"] == "ok"
    assert body["inputCompleteness"]["sessions"]["rowCount"] == 1


@pytest.mark.asyncio
async def test_report_packet_excludes_shoots_without_transcript(
    client: AsyncClient, db_session: AsyncSession
):
    create = await client.post(
        "/api/admin/campaigns",
        headers=admin_headers(),
        json={"name": "No-Transcript Campaign"},
    )
    campaign_id = create.json()["id"]

    shoot = Shoot(
        id="shoot-report-packet-2",
        name="Untranscribed shoot",
        campaign_id=campaign_id,
        diarized_transcript=None,
    )
    db_session.add(shoot)
    await db_session.commit()

    response = await client.get(
        f"/api/campaigns/{campaign_id}/report-packet",
        headers=admin_headers(),
    )
    body = response.json()

    assert body["sessions"] == []
    assert body["inputCompleteness"]["sessions"]["status"] == "missing"


@pytest.mark.asyncio
async def test_report_packet_excludes_shoots_linked_to_other_campaigns(
    client: AsyncClient, db_session: AsyncSession
):
    campaign_a = (
        await client.post(
            "/api/admin/campaigns",
            headers=admin_headers(),
            json={"name": "Campaign A"},
        )
    ).json()["id"]
    campaign_b = (
        await client.post(
            "/api/admin/campaigns",
            headers=admin_headers(),
            json={"name": "Campaign B"},
        )
    ).json()["id"]

    shoot = Shoot(
        id="shoot-report-packet-3",
        name="Belongs to campaign B",
        campaign_id=campaign_b,
        diarized_transcript="Transcript for B.",
    )
    db_session.add(shoot)
    await db_session.commit()

    response = await client.get(
        f"/api/campaigns/{campaign_a}/report-packet",
        headers=admin_headers(),
    )
    body = response.json()

    assert body["sessions"] == []


@pytest.mark.asyncio
async def test_report_packet_window_and_sources_passthrough(client: AsyncClient):
    create = await client.post(
        "/api/admin/campaigns",
        headers=admin_headers(),
        json={"name": "Window Campaign"},
    )
    campaign_id = create.json()["id"]

    response = await client.get(
        f"/api/campaigns/{campaign_id}/report-packet",
        headers=admin_headers(),
        params={
            "windowStart": "2026-08-01",
            "windowEnd": "2026-08-31",
            "sources": ["linkedin", "hubspot"],
        },
    )
    body = response.json()

    assert body["windowStart"] == "2026-08-01"
    assert body["windowEnd"] == "2026-08-31"
    assert body["sources"] == ["linkedin", "hubspot"]


@pytest.mark.asyncio
async def test_report_packet_includes_export_warehouse_session(
    client: AsyncClient, db_session: AsyncSession
):
    create = await client.post(
        "/api/admin/campaigns",
        headers=admin_headers(),
        json={"name": "Zoom Warehouse Campaign"},
    )
    campaign_id = create.json()["id"]

    db_session.add(
        ExportSession(
            platform_tool_program_id="clxyz_program_cpr32",
            campaign_id=campaign_id,
            kind="WEBINAR",
            title="HER2+ Live Session",
            session_date=datetime(2026, 8, 15, 17, 0, tzinfo=timezone.utc),
            zoom_meeting_id="81234567890",
            zoom_uuid="AbCdEf==",
            transcript_text="Speaker [00:00]:\nWelcome to the webinar.",
        )
    )
    await db_session.commit()

    response = await client.get(
        f"/api/campaigns/{campaign_id}/report-packet",
        headers=admin_headers(),
    )
    assert response.status_code == 200
    body = response.json()

    assert len(body["sessions"]) == 1
    session = body["sessions"][0]
    assert session["platformToolProgramId"] == "clxyz_program_cpr32"
    assert session["kind"] == "WEBINAR"
    assert session["title"] == "HER2+ Live Session"
    assert session["zoomMeetingUuid"] == "AbCdEf=="
    assert session["transcriptText"] == "Speaker [00:00]:\nWelcome to the webinar."
    assert body["inputCompleteness"]["sessions"]["status"] == "ok"
    assert body["inputCompleteness"]["sessions"]["rowCount"] == 1
    assert body["inputCompleteness"]["sessions"]["fetchedAt"] is not None


@pytest.mark.asyncio
async def test_report_packet_includes_export_survey_responses(
    client: AsyncClient, db_session: AsyncSession
):
    create = await client.post(
        "/api/admin/campaigns",
        headers=admin_headers(),
        json={"name": "Survey Warehouse Campaign"},
    )
    campaign_id = create.json()["id"]

    db_session.add(
        ExportSurveyResponse(
            dedupe_key="submission:survey_cpr32_1",
            campaign_id=campaign_id,
            platform_tool_program_id="clxyz_program_cpr32",
            respondent_id="user_1",
            source="platform",
            survey_type="POST_TEST",
            submitted_at=datetime(2026, 8, 15, 19, 0, tzinfo=timezone.utc),
            submission_id="survey_cpr32_1",
            answers={"nps": 9, "q1": "excellent"},
        )
    )
    await db_session.commit()

    response = await client.get(
        f"/api/campaigns/{campaign_id}/report-packet",
        headers=admin_headers(),
    )
    body = response.json()

    assert len(body["surveyResponses"]) == 1
    survey = body["surveyResponses"][0]
    assert survey["respondentId"] == "user_1"
    assert survey["source"] == "platform"
    assert survey["surveyType"] == "POST_TEST"
    assert survey["answers"] == {"nps": 9, "q1": "excellent"}
    assert body["inputCompleteness"]["surveyResponses"]["status"] == "ok"
    assert body["inputCompleteness"]["surveyResponses"]["rowCount"] == 1


@pytest.mark.asyncio
async def test_report_packet_zoom_sessions_win_over_shoots(
    client: AsyncClient, db_session: AsyncSession
):
    """Uche rule: Zoom warehouse first; do not union shoot transcripts."""
    create = await client.post(
        "/api/admin/campaigns",
        headers=admin_headers(),
        json={"name": "Zoom Wins Campaign"},
    )
    campaign_id = create.json()["id"]

    db_session.add(
        ExportSession(
            platform_tool_program_id="clxyz_zoom_wins",
            campaign_id=campaign_id,
            kind="WEBINAR",
            title="Zoom Session",
            zoom_uuid="zoom-uuid-1",
            transcript_text="Zoom transcript body.",
        )
    )
    db_session.add(
        Shoot(
            id="shoot-report-packet-zoom-wins",
            name="Shoot Should Be Ignored",
            campaign_id=campaign_id,
            shoot_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
            diarized_transcript="Shoot transcript should not appear.",
        )
    )
    await db_session.commit()

    response = await client.get(
        f"/api/campaigns/{campaign_id}/report-packet",
        headers=admin_headers(),
    )
    body = response.json()

    assert len(body["sessions"]) == 1
    assert body["sessions"][0]["title"] == "Zoom Session"
    assert body["sessions"][0]["transcriptText"] == "Zoom transcript body."
    assert body["sessions"][0]["platformToolProgramId"] == "clxyz_zoom_wins"


@pytest.mark.asyncio
async def test_report_packet_export_session_without_transcript_text_still_listed(
    client: AsyncClient, db_session: AsyncSession
):
    """Session row counts even if transcript_text empty (S3 key-only ingest)."""
    create = await client.post(
        "/api/admin/campaigns",
        headers=admin_headers(),
        json={"name": "Key-Only Transcript Campaign"},
    )
    campaign_id = create.json()["id"]

    db_session.add(
        ExportSession(
            platform_tool_program_id="clxyz_key_only",
            campaign_id=campaign_id,
            title="Awaiting VTT strip",
            transcript_s3_key="zoom-recordings/x/file.vtt",
            transcript_text=None,
        )
    )
    await db_session.commit()

    response = await client.get(
        f"/api/campaigns/{campaign_id}/report-packet",
        headers=admin_headers(),
    )
    body = response.json()

    assert len(body["sessions"]) == 1
    assert body["sessions"][0]["transcriptText"] == ""
    assert body["inputCompleteness"]["sessions"]["status"] == "ok"


@pytest.mark.asyncio
async def test_report_packet_fills_transcript_from_s3_store_when_text_missing(
    client: AsyncClient, db_session: AsyncSession
):
    create = await client.post(
        "/api/admin/campaigns",
        headers=admin_headers(),
        json={"name": "S3 Fill Campaign"},
    )
    campaign_id = create.json()["id"]

    key = "zoom-recordings/cpr32/file1.vtt"
    db_session.add(
        ExportSession(
            platform_tool_program_id="clxyz_s3_fill",
            campaign_id=campaign_id,
            title="Needs GetObject",
            transcript_s3_key=key,
            transcript_text=None,
        )
    )
    await db_session.commit()

    sample_vtt = (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "Dr. Lee: Hello from S3.\n"
    )
    store = MemoryTranscriptStore({key: sample_vtt})

    with patch(
        "services.report_packet._resolve_transcript_store",
        return_value=store,
    ):
        response = await client.get(
            f"/api/campaigns/{campaign_id}/report-packet",
            headers=admin_headers(),
        )

    body = response.json()
    assert len(body["sessions"]) == 1
    assert "Dr. Lee: Hello from S3." in body["sessions"][0]["transcriptText"]
    assert "WEBVTT" not in body["sessions"][0]["transcriptText"]
    assert body["inputCompleteness"]["sessions"]["status"] == "ok"


@pytest.mark.asyncio
async def test_report_packet_s3_failure_leaves_empty_transcript_not_500(
    client: AsyncClient, db_session: AsyncSession
):
    create = await client.post(
        "/api/admin/campaigns",
        headers=admin_headers(),
        json={"name": "S3 Fail Campaign"},
    )
    campaign_id = create.json()["id"]

    db_session.add(
        ExportSession(
            platform_tool_program_id="clxyz_s3_fail",
            campaign_id=campaign_id,
            title="Missing object",
            transcript_s3_key="zoom-recordings/missing.vtt",
            transcript_text=None,
        )
    )
    await db_session.commit()

    with patch(
        "services.report_packet._resolve_transcript_store",
        return_value=MemoryTranscriptStore({}),
    ):
        response = await client.get(
            f"/api/campaigns/{campaign_id}/report-packet",
            headers=admin_headers(),
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["sessions"]) == 1
    assert body["sessions"][0]["transcriptText"] == ""
    assert body["inputCompleteness"]["sessions"]["status"] == "ok"


@pytest.mark.asyncio
async def test_report_packet_ignores_warehouse_rows_for_other_campaigns(
    client: AsyncClient, db_session: AsyncSession
):
    campaign_a = (
        await client.post(
            "/api/admin/campaigns",
            headers=admin_headers(),
            json={"name": "Warehouse Campaign A"},
        )
    ).json()["id"]
    campaign_b = (
        await client.post(
            "/api/admin/campaigns",
            headers=admin_headers(),
            json={"name": "Warehouse Campaign B"},
        )
    ).json()["id"]

    db_session.add(
        ExportSession(
            platform_tool_program_id="clxyz_belongs_to_b",
            campaign_id=campaign_b,
            title="B only",
            transcript_text="Only for B.",
        )
    )
    db_session.add(
        ExportSurveyResponse(
            dedupe_key="submission:b_only",
            campaign_id=campaign_b,
            respondent_id="user_b",
            source="platform",
            answers={"x": 1},
        )
    )
    await db_session.commit()

    response = await client.get(
        f"/api/campaigns/{campaign_a}/report-packet",
        headers=admin_headers(),
    )
    body = response.json()

    assert body["sessions"] == []
    assert body["surveyResponses"] == []
    assert body["inputCompleteness"]["sessions"]["status"] == "missing"
    assert body["inputCompleteness"]["surveyResponses"]["status"] == "missing"
