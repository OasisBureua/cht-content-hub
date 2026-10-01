"""CPR-9: S3 VTT object → export_sessions.transcript_text."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.campaign import Campaign
from models.export_warehouse import ExportSession
from services.export_ingest.transcript_s3 import (
    MemoryTranscriptStore,
    TranscriptStoreError,
)
from services.export_ingest.vtt_object import (
    apply_vtt_object,
    parse_vtt_object_key,
    stripped_text_hash,
)

TINY_VTT = """WEBVTT

1
00:00:00.000 --> 00:00:02.000
Hello from Zoom
"""

KEY = "zoom-recordings/clprogvtt/m-1/f-1.vtt"


async def _linked_session(
    db: AsyncSession,
    *,
    program_id: str = "clprogvtt",
    key: str | None = None,
    text: str | None = None,
    campaign: bool = True,
) -> ExportSession:
    campaign_id = None
    if campaign:
        row = Campaign(name="VTT Campaign", program_name="VTT")
        db.add(row)
        await db.flush()
        campaign_id = row.id
    session = ExportSession(
        platform_tool_program_id=program_id,
        campaign_id=campaign_id,
        title="Linked",
        session_date=datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc),
        transcript_s3_key=key,
        transcript_text=text,
    )
    db.add(session)
    await db.flush()
    return session


def test_parse_vtt_object_key_accepts_and_rejects():
    assert parse_vtt_object_key(KEY) == ("clprogvtt", "m-1", "f-1")
    encoded = "zoom-recordings/clprogvtt/m-1/f%2D1.vtt"
    assert parse_vtt_object_key(encoded) == ("clprogvtt", "m-1", "f-1")
    assert parse_vtt_object_key("zoom-recordings/unlinked/m/f.vtt") == (
        "unlinked",
        "m",
        "f",
    )
    assert parse_vtt_object_key("zoom-recordings/p/m/f.mp4") is None
    assert parse_vtt_object_key("other/p/m/f.vtt") is None
    assert parse_vtt_object_key("zoom-recordings/only.vtt") is None


@pytest.mark.asyncio
async def test_linked_vtt_strips_cues_and_writes(db_session: AsyncSession):
    session = await _linked_session(db_session)
    store = MemoryTranscriptStore({KEY: TINY_VTT})

    result = await apply_vtt_object(db_session, store, KEY)
    await db_session.commit()

    assert result.status == "applied"
    assert result.session_id == session.id
    await db_session.refresh(session)
    assert session.transcript_s3_key == KEY
    assert session.transcript_text == "Hello from Zoom"
    assert "WEBVTT" not in session.transcript_text
    assert "-->" not in session.transcript_text


@pytest.mark.asyncio
async def test_same_body_twice_hash_skips(db_session: AsyncSession):
    store = MemoryTranscriptStore({KEY: TINY_VTT})
    session = await _linked_session(db_session)
    first = await apply_vtt_object(db_session, store, KEY)
    second = await apply_vtt_object(db_session, store, KEY)
    await db_session.commit()

    assert first.status == "applied"
    assert second.status == "hash_skip"
    assert second.session_id == session.id
    assert stripped_text_hash(session.transcript_text) == stripped_text_hash(
        "Hello from Zoom"
    )


@pytest.mark.asyncio
async def test_unlinked_and_missing_row_do_not_insert(db_session: AsyncSession):
    store = MemoryTranscriptStore(
        {
            "zoom-recordings/unlinked/m/f.vtt": TINY_VTT,
            "zoom-recordings/missing/m/f.vtt": TINY_VTT,
        }
    )

    unlinked = await apply_vtt_object(
        db_session, store, "zoom-recordings/unlinked/m/f.vtt"
    )
    missing = await apply_vtt_object(
        db_session, store, "zoom-recordings/missing/m/f.vtt"
    )
    await db_session.commit()

    assert unlinked.status == "skipped_unlinked"
    assert missing.status == "skipped_no_session"
    rows = (
        await db_session.execute(select(ExportSession))
    ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_null_campaign_id_skips_without_write(db_session: AsyncSession):
    session = await _linked_session(db_session, campaign=False)
    store = MemoryTranscriptStore({KEY: TINY_VTT})

    result = await apply_vtt_object(db_session, store, KEY)
    await db_session.commit()

    assert result.status == "skipped_no_campaign"
    await db_session.refresh(session)
    assert session.transcript_text is None


@pytest.mark.asyncio
async def test_get_object_failure_raises(db_session: AsyncSession):
    await _linked_session(db_session)
    store = MemoryTranscriptStore()

    with pytest.raises(TranscriptStoreError):
        await apply_vtt_object(db_session, store, KEY)


@pytest.mark.asyncio
async def test_lookup_by_existing_transcript_s3_key(db_session: AsyncSession):
    other_program = "other-prog"
    session = await _linked_session(
        db_session, program_id=other_program, key=KEY
    )
    store = MemoryTranscriptStore({KEY: TINY_VTT})

    result = await apply_vtt_object(db_session, store, KEY)
    await db_session.commit()

    assert result.status == "applied"
    assert result.session_id == session.id
    await db_session.refresh(session)
    assert session.transcript_text == "Hello from Zoom"
