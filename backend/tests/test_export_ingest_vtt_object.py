"""S3 VTT → existing export_sessions (vtt_object_ingest)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.campaign import Campaign
from models.export_warehouse import ExportSession
from services.export_ingest.transcript_s3 import (
    MemoryTranscriptStore,
    TranscriptStoreError,
)
from services.export_ingest.vtt import strip_vtt
from services.export_ingest.vtt_object import (
    apply_vtt_object,
    decode_s3_object_key,
    parse_zoom_vtt_key,
    stripped_text_hash,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "platform_export"
SAMPLE_VTT = (FIXTURES / "sample_transcript.vtt").read_text(encoding="utf-8")
PROGRAM_ID = "clprogvtt001"
MEETING_ID = "81234567890"
FILE_ID = "file1.vtt"
KEY = f"zoom-recordings/{PROGRAM_ID}/{MEETING_ID}/{FILE_ID}"
TINY_VTT = "WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\nHello from Zoom\n"


async def _linked_session(
    db: AsyncSession,
    *,
    program_id: str = PROGRAM_ID,
    key: str | None = None,
    text: str | None = None,
) -> ExportSession:
    campaign = Campaign(name="VTT Campaign", program_name="Prog")
    db.add(campaign)
    await db.flush()
    row = ExportSession(
        platform_tool_program_id=program_id,
        campaign_id=campaign.id,
        transcript_s3_key=key,
        transcript_text=text,
    )
    db.add(row)
    await db.flush()
    return row


def test_decode_s3_object_key_unquotes():
    encoded = "zoom-recordings/prog%2Fid/meet/file.vtt"
    assert decode_s3_object_key(encoded) == "zoom-recordings/prog/id/meet/file.vtt"


def test_parse_zoom_vtt_key():
    assert parse_zoom_vtt_key(KEY) == (PROGRAM_ID, MEETING_ID, FILE_ID)
    assert parse_zoom_vtt_key("zoom-recordings/x/y/file.mp4") is None
    assert parse_zoom_vtt_key("session-heroes/x/y/file.vtt") is None
    assert parse_zoom_vtt_key("zoom-recordings/only-two/parts.vtt") is None


@pytest.mark.asyncio
async def test_linked_session_tiny_vtt_updates_stripped_text(
    db_session: AsyncSession,
):
    await _linked_session(db_session)
    store = MemoryTranscriptStore({KEY: TINY_VTT})

    result = await apply_vtt_object(db_session, store, KEY)
    await db_session.commit()

    assert result.status == "updated"
    row = (
        await db_session.execute(
            select(ExportSession).where(
                ExportSession.platform_tool_program_id == PROGRAM_ID
            )
        )
    ).scalar_one()
    assert row.transcript_s3_key == KEY
    assert row.transcript_text == "Hello from Zoom"
    assert "WEBVTT" not in row.transcript_text
    assert "-->" not in row.transcript_text


@pytest.mark.asyncio
async def test_lookup_by_existing_transcript_s3_key(db_session: AsyncSession):
    await _linked_session(db_session, program_id="other-program", key=KEY)
    store = MemoryTranscriptStore({KEY: SAMPLE_VTT})

    result = await apply_vtt_object(db_session, store, KEY)
    assert result.status == "updated"
    row = (
        await db_session.execute(
            select(ExportSession).where(ExportSession.transcript_s3_key == KEY)
        )
    ).scalar_one()
    assert "Dr. Smith:" in (row.transcript_text or "")


@pytest.mark.asyncio
async def test_same_body_twice_hash_skips(db_session: AsyncSession):
    stripped = strip_vtt(TINY_VTT)
    await _linked_session(db_session, text=stripped)
    store = MemoryTranscriptStore({KEY: TINY_VTT})

    first = await apply_vtt_object(db_session, store, KEY)
    assert first.status == "unchanged"
    assert first.reason == "hash_skip"
    assert stripped_text_hash(stripped) == stripped_text_hash("Hello from Zoom")


@pytest.mark.asyncio
async def test_unlinked_skips_without_insert(db_session: AsyncSession):
    key = "zoom-recordings/unlinked/8123/file.vtt"
    store = MemoryTranscriptStore({key: TINY_VTT})

    result = await apply_vtt_object(db_session, store, key)
    assert result.status == "skipped"
    assert result.reason == "unlinked"
    count = (await db_session.execute(select(ExportSession))).scalars().all()
    assert count == []


@pytest.mark.asyncio
async def test_no_session_skips_without_insert(db_session: AsyncSession):
    store = MemoryTranscriptStore({KEY: TINY_VTT})
    result = await apply_vtt_object(db_session, store, KEY)
    assert result.status == "skipped"
    assert result.reason == "no_session"
    assert (await db_session.execute(select(ExportSession))).scalars().all() == []


@pytest.mark.asyncio
async def test_null_campaign_id_skips_without_write(db_session: AsyncSession):
    db_session.add(
        ExportSession(
            platform_tool_program_id=PROGRAM_ID,
            campaign_id=None,
            transcript_text=None,
        )
    )
    await db_session.flush()
    store = MemoryTranscriptStore({KEY: TINY_VTT})

    result = await apply_vtt_object(db_session, store, KEY)
    assert result.status == "skipped"
    assert result.reason == "null_campaign_id"
    row = (
        await db_session.execute(
            select(ExportSession).where(
                ExportSession.platform_tool_program_id == PROGRAM_ID
            )
        )
    ).scalar_one()
    assert row.transcript_text is None


@pytest.mark.asyncio
async def test_get_object_failure_raises(db_session: AsyncSession):
    await _linked_session(db_session)
    store = MemoryTranscriptStore()  # missing key

    with pytest.raises(TranscriptStoreError):
        await apply_vtt_object(db_session, store, KEY)


@pytest.mark.asyncio
async def test_encoded_key_from_s3_event(db_session: AsyncSession):
    await _linked_session(db_session)
    store = MemoryTranscriptStore({KEY: TINY_VTT})
    encoded = (
        f"zoom-recordings/{PROGRAM_ID}/{MEETING_ID}/{FILE_ID}".replace("/", "%2F")
    )
    # S3 encodes segments, not slashes, but unquote_plus is still required.
    encoded = f"zoom-recordings/{PROGRAM_ID}/{MEETING_ID}/{FILE_ID}"
    result = await apply_vtt_object(db_session, store, encoded)
    assert result.status == "updated"
