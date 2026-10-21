"""CPR-51: per-source counts for the Generate card."""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import api_headers
from models.export_warehouse import (
    ExportAttendanceEvent,
    ExportRegistration,
    ExportSession,
)


async def _campaign(client: AsyncClient, name: str) -> int:
    response = await client.post("/api/admin/campaigns", headers=api_headers(), json={"name": name})
    return response.json()["id"]


def _joined(campaign_id: int, email: str, *, specialty: str | None, institution: str | None):
    return ExportAttendanceEvent(
        dedupe_key=f"rollup:prog-inputs:e:{email}",
        platform_tool_program_id="prog-inputs",
        campaign_id=campaign_id,
        source="REPORT_IMPORT",
        event="JOINED",
        occurred_at=datetime(2026, 10, 15, 22, 0, tzinfo=timezone.utc),
        participant_email=email,
        duration_seconds=600,
        specialty=specialty,
        institution=institution,
    )


@pytest.mark.asyncio
async def test_report_inputs_requires_api_key(http_client: AsyncClient):
    response = await http_client.get("/api/admin/campaigns/1/report-inputs")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_report_inputs_404_for_missing_campaign(client: AsyncClient):
    response = await client.get("/api/admin/campaigns/999999/report-inputs", headers=api_headers())
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_report_inputs_counts_sources_without_downloading_transcripts(
    client: AsyncClient, db_session: AsyncSession
):
    campaign_id = await _campaign(client, "Inputs Campaign")
    db_session.add_all(
        [
            ExportSession(
                platform_tool_program_id="prog-inputs",
                campaign_id=campaign_id,
                title="Live",
                session_date=date(2026, 10, 15),
                transcript_s3_key="zoom-recordings/inputs/file.vtt",
                transcript_text=None,
            ),
            ExportSession(
                platform_tool_program_id="prog-inputs-2",
                campaign_id=campaign_id,
                title="No recording",
                session_date=date(2026, 10, 15),
            ),
            ExportRegistration(
                dedupe_key="prog-inputs|u1",
                platform_tool_program_id="prog-inputs",
                campaign_id=campaign_id,
                user_id="u1",
                registered_at=datetime(2026, 10, 14, tzinfo=timezone.utc),
                status="APPROVED",
                specialty="Oncology",
            ),
            _joined(campaign_id, "a@example.com", specialty="Oncology", institution=None),
            _joined(campaign_id, "b@example.com", specialty=None, institution=None),
        ]
    )
    await db_session.commit()

    with patch(
        "services.report_packet._resolve_transcript_store",
        side_effect=AssertionError("report inputs must not download transcripts"),
    ):
        response = await client.get(
            f"/api/admin/campaigns/{campaign_id}/report-inputs", headers=api_headers()
        )

    assert response.status_code == 200
    body = response.json()
    completeness = body["inputCompleteness"]
    assert completeness["sessions"]["rowCount"] == 2
    assert completeness["transcripts"] == {
        "fetchedAt": completeness["sessions"]["fetchedAt"],
        "rowCount": 1,
        "status": "ok",
    }
    assert completeness["attendance"]["rowCount"] == 2
    assert completeness["registrations"]["rowCount"] == 1
    assert completeness["surveyResponses"]["status"] == "missing"
    assert completeness["kols"]["status"] == "missing"
    assert body["registeredCount"] == 1
    assert body["attendedCount"] == 2
    assert body["attendeesWithProfile"] == 1
    assert "sessions" not in body


@pytest.mark.asyncio
async def test_report_inputs_only_lists_requested_sources(
    client: AsyncClient, db_session: AsyncSession
):
    campaign_id = await _campaign(client, "Inputs Sources Campaign")
    db_session.add(_joined(campaign_id, "c@example.com", specialty="Cardiology", institution="CHM"))
    await db_session.commit()

    response = await client.get(
        f"/api/admin/campaigns/{campaign_id}/report-inputs",
        headers=api_headers(),
        params={"sources": ["surveys"]},
    )

    body = response.json()
    assert set(body["inputCompleteness"]) == {"surveyResponses", "template"}
    assert body["sources"] == ["surveys"]
    assert body["attendedCount"] is None
    assert body["attendeesWithProfile"] is None


@pytest.mark.asyncio
async def test_report_inputs_applies_the_window(client: AsyncClient, db_session: AsyncSession):
    campaign_id = await _campaign(client, "Inputs Window Campaign")
    db_session.add_all(
        [
            ExportSession(
                platform_tool_program_id="prog-old",
                campaign_id=campaign_id,
                title="Old",
                session_date=date(2026, 8, 1),
                transcript_text="Earlier session.",
            ),
            ExportSession(
                platform_tool_program_id="prog-new",
                campaign_id=campaign_id,
                title="New",
                session_date=date(2026, 10, 15),
                transcript_text="Recent session.",
            ),
        ]
    )
    await db_session.commit()

    response = await client.get(
        f"/api/admin/campaigns/{campaign_id}/report-inputs",
        headers=api_headers(),
        params={"windowStart": "2026-09-16", "windowEnd": "2026-10-16", "sources": ["sessions"]},
    )

    body = response.json()
    assert body["windowStart"] == "2026-09-16"
    assert body["inputCompleteness"]["sessions"]["rowCount"] == 1
    assert body["inputCompleteness"]["transcripts"]["rowCount"] == 1
