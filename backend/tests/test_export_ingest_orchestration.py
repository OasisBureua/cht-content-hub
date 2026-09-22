"""Phase F: campaign ingest orchestration + admin export-ingest route."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings
from conftest import api_headers
from models.export_warehouse import ExportIngestRun, ExportSession
from services.export_ingest.client_fixture import FixtureExportClient
from services.export_ingest.ingest import (
    ExportIngestConfigError,
    ingest_campaign,
    ingest_campaigns_batch,
    memory_runtime_for_tests,
    resolve_export_ingest_runtime,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "platform_export"
SAMPLE_KEY = (
    "zoom-recordings/clxyz001programcuid0001/81234567890/file1.vtt"
)
SAMPLE_VTT = (FIXTURES / "sample_transcript.vtt").read_text(encoding="utf-8")


def admin_headers(**extra: str) -> dict[str, str]:
    return api_headers(**extra)


@pytest.mark.asyncio
async def test_ingest_campaign_from_fixture_client(db_session: AsyncSession):
    create = await _create_campaign_via_orm(db_session, campaign_id=42)
    assert create == 42

    client = FixtureExportClient(directory=FIXTURES)
    runtime = memory_runtime_for_tests(
        client=client, transcript_objects={SAMPLE_KEY: SAMPLE_VTT}
    )
    run = await ingest_campaign(
        db_session,
        42,
        client=runtime.client,
        transcript_store=runtime.transcript_store,
        trigger="fixture",
    )
    await db_session.commit()

    assert run.status == "success"
    assert run.sessions_upserted == 1
    session = (await db_session.execute(select(ExportSession))).scalar_one()
    assert session.transcript_text is not None
    assert "Dr. Smith:" in session.transcript_text


@pytest.mark.asyncio
async def test_ingest_campaign_404_for_missing_campaign(db_session: AsyncSession):
    client = FixtureExportClient(directory=FIXTURES)
    with pytest.raises(Exception) as exc:
        await ingest_campaign(db_session, 404404, client=client)
    assert getattr(exc.value, "status_code", None) == 404


def test_resolve_runtime_http_requires_base_url():
    with pytest.raises(ExportIngestConfigError, match="PLATFORM_EXPORT_BASE_URL"):
        resolve_export_ingest_runtime(Settings(), source="http")


def test_resolve_runtime_fixture_requires_dir():
    with pytest.raises(ExportIngestConfigError, match="PLATFORM_EXPORT_FIXTURE_DIR"):
        resolve_export_ingest_runtime(Settings(), source="fixture")


def test_resolve_runtime_fixture_ok():
    settings = Settings(platform_export_fixture_dir=str(FIXTURES))
    runtime = resolve_export_ingest_runtime(settings, source="fixture")
    assert isinstance(runtime.client, FixtureExportClient)


@pytest.mark.asyncio
async def test_ingest_campaigns_batch_continues_on_failure(
    db_session: AsyncSession,
):
    await _create_campaign_via_orm(db_session, campaign_id=42)
    await _create_campaign_via_orm(db_session, campaign_id=99)

    client = FixtureExportClient(directory=FIXTURES)
    batch = await ingest_campaigns_batch(
        db_session,
        client=client,
        transcript_store=memory_runtime_for_tests(
            client=client, transcript_objects={SAMPLE_KEY: SAMPLE_VTT}
        ).transcript_store,
        campaign_ids=[42, 99],
        trigger="schedule",
    )
    await db_session.commit()

    assert batch.processed == 2
    assert batch.succeeded == 1
    assert batch.failed == 1
    by_id = {row.campaign_id: row for row in batch.results}
    assert by_id[42].status == "success"
    assert by_id[99].status == "error"
    assert by_id[99].error


@pytest.mark.asyncio
async def test_admin_export_ingest_endpoint(client: AsyncClient, db_session: AsyncSession):
    create = await client.post(
        "/api/admin/campaigns",
        headers=admin_headers(),
        json={"name": "Export Ingest Campaign"},
    )
    assert create.status_code in (200, 201)
    campaign_id = create.json()["id"]

    # Align fixture packet campaign id with the created campaign.
    packet_client = FixtureExportClient(directory=FIXTURES)
    packet = await packet_client.fetch_campaign_packet(42)
    packet = packet.model_copy(update={"campaign_id": campaign_id})
    runtime_client = FixtureExportClient()
    runtime_client.put(packet)
    runtime = memory_runtime_for_tests(
        client=runtime_client,
        transcript_objects={SAMPLE_KEY: SAMPLE_VTT},
    )

    with patch(
        "admin.router.resolve_export_ingest_runtime_http",
        return_value=runtime,
    ):
        response = await client.post(
            f"/api/admin/campaigns/{campaign_id}/export-ingest",
            headers=admin_headers(),
            params={"source": "fixture"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "success"
    assert body["campaignId"] == campaign_id
    assert body["sessionsUpserted"] == 1
    assert body["attendanceUpserted"] == 3

    count = (
        await db_session.execute(select(func.count()).select_from(ExportSession))
    ).scalar_one()
    assert count == 1
    runs = (
        await db_session.execute(select(func.count()).select_from(ExportIngestRun))
    ).scalar_one()
    assert runs == 1


@pytest.mark.asyncio
async def test_admin_export_ingest_requires_api_key(http_client: AsyncClient):
    response = await http_client.post("/api/admin/campaigns/1/export-ingest")
    assert response.status_code == 401


async def _create_campaign_via_orm(db_session: AsyncSession, *, campaign_id: int) -> int:
    from models.campaign import Campaign

    db_session.add(Campaign(id=campaign_id, name=f"Campaign {campaign_id}"))
    await db_session.flush()
    return campaign_id
