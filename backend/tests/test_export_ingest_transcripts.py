"""Phase D: transcript S3 store + ingest enrichment tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.campaign import Campaign
from models.export_warehouse import ExportSession
from schemas.platform_export import ExportSession as ExportSessionDTO
from schemas.platform_export import PlatformExportPacket
from services.export_ingest.transcript_s3 import (
    MemoryTranscriptStore,
    S3TranscriptStore,
    TranscriptStoreError,
)
from services.export_ingest.upsert import enrich_session_transcript, ingest_packet

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "platform_export"
SAMPLE_VTT = (FIXTURES / "sample_transcript.vtt").read_text(encoding="utf-8")
SAMPLE_KEY = (
    "zoom-recordings/clxyz001programcuid0001/81234567890/file1.vtt"
)


def test_memory_store_round_trip():
    store = MemoryTranscriptStore({SAMPLE_KEY: SAMPLE_VTT})
    assert store.get_vtt(SAMPLE_KEY).startswith("WEBVTT")


def test_memory_store_missing_key():
    store = MemoryTranscriptStore()
    with pytest.raises(TranscriptStoreError):
        store.get_vtt("missing.vtt")


def test_s3_store_uses_get_object():
    body = MagicMock()
    body.read.return_value = SAMPLE_VTT.encode("utf-8")
    client = MagicMock()
    client.get_object.return_value = {"Body": body}

    store = S3TranscriptStore("platform-transcripts", client=client)
    text = store.get_vtt(SAMPLE_KEY)

    client.get_object.assert_called_once_with(
        Bucket="platform-transcripts", Key=SAMPLE_KEY
    )
    assert text.startswith("WEBVTT")


def test_s3_store_requires_bucket():
    with pytest.raises(ValueError):
        S3TranscriptStore("")


def test_s3_store_wraps_client_errors():
    client = MagicMock()
    client.get_object.side_effect = RuntimeError("AccessDenied")
    store = S3TranscriptStore("bucket", client=client)
    with pytest.raises(TranscriptStoreError, match="AccessDenied"):
        store.get_vtt("k.vtt")


def test_enrich_session_transcript_strips_vtt():
    store = MemoryTranscriptStore({SAMPLE_KEY: SAMPLE_VTT})
    session = ExportSessionDTO(
        platform_tool_program_id="p1",
        transcript_s3_key=SAMPLE_KEY,
        transcript_text=None,
    )
    enriched = enrich_session_transcript(session, store)
    assert enriched.transcript_text is not None
    assert "Dr. Smith:" in enriched.transcript_text
    assert "-->" not in enriched.transcript_text


def test_enrich_skips_when_text_already_present():
    store = MemoryTranscriptStore({SAMPLE_KEY: SAMPLE_VTT})
    session = ExportSessionDTO(
        platform_tool_program_id="p1",
        transcript_s3_key=SAMPLE_KEY,
        transcript_text="already parsed",
    )
    assert enrich_session_transcript(session, store).transcript_text == "already parsed"


@pytest.mark.asyncio
async def test_ingest_fills_transcript_text_from_store(db_session: AsyncSession):
    raw = json.loads(
        (FIXTURES / "campaign_42_packet.json").read_text(encoding="utf-8")
    )
    packet = PlatformExportPacket.model_validate(raw)
    db_session.add(Campaign(id=packet.campaign_id, name="Campaign 42"))
    await db_session.flush()

    store = MemoryTranscriptStore({SAMPLE_KEY: SAMPLE_VTT})
    await ingest_packet(db_session, packet, transcript_store=store)
    await db_session.commit()

    session = (await db_session.execute(select(ExportSession))).scalar_one()
    assert session.transcript_s3_key == SAMPLE_KEY
    assert session.transcript_text is not None
    assert "Thank you for joining us." in session.transcript_text
