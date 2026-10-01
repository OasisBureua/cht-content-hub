"""Apply one Zoom VTT S3 object to an existing export_sessions row.

Used by ``vtt_object_ingest``. Does not create sessions — unlinked keys,
missing rows, and null campaign_id are successful no-ops. GetObject
failures propagate so the async Lambda retries then DLQ.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from urllib.parse import unquote_plus

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.export_warehouse import ExportSession
from services.export_ingest.transcript_s3 import TranscriptStore
from services.export_ingest.vtt import strip_vtt

log = logging.getLogger(__name__)

_PREFIX = "zoom-recordings/"
_SUFFIX = ".vtt"


@dataclass(frozen=True)
class VttObjectResult:
    key: str
    status: str
    session_id: int | None = None


def decode_object_key(key: str) -> str:
    return unquote_plus(key or "").strip()


def parse_vtt_object_key(key: str) -> tuple[str, str, str] | None:
    """Return (program_id, meeting_id, file_id) or None if the key is not ours."""
    decoded = decode_object_key(key)
    if not decoded.startswith(_PREFIX) or not decoded.lower().endswith(_SUFFIX):
        return None
    parts = decoded.split("/")
    if len(parts) != 4 or not parts[1] or not parts[2] or not parts[3]:
        return None
    file_id = parts[3][: -len(_SUFFIX)]
    if not file_id:
        return None
    return parts[1], parts[2], file_id


def stripped_text_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


async def apply_vtt_object(
    db: AsyncSession,
    store: TranscriptStore,
    key: str,
) -> VttObjectResult:
    decoded = decode_object_key(key)
    parsed = parse_vtt_object_key(decoded)
    if parsed is None:
        return VttObjectResult(key=decoded, status="ignored")

    program_id, _meeting_id, _file_id = parsed
    if program_id == "unlinked":
        return VttObjectResult(key=decoded, status="skipped_unlinked")

    raw = store.get_vtt(decoded)
    stripped = strip_vtt(raw)

    row = (
        await db.execute(
            select(ExportSession).where(ExportSession.transcript_s3_key == decoded)
        )
    ).scalar_one_or_none()
    if row is None:
        row = (
            await db.execute(
                select(ExportSession).where(
                    ExportSession.platform_tool_program_id == program_id
                )
            )
        ).scalar_one_or_none()

    if row is None:
        return VttObjectResult(key=decoded, status="skipped_no_session")
    if row.campaign_id is None:
        return VttObjectResult(
            key=decoded, status="skipped_no_campaign", session_id=row.id
        )

    if stripped_text_hash(row.transcript_text or "") == stripped_text_hash(stripped):
        return VttObjectResult(key=decoded, status="hash_skip", session_id=row.id)

    row.transcript_s3_key = decoded
    row.transcript_text = stripped
    await db.flush()
    log.info(
        "vtt_object applied session_id=%s key=%s",
        row.id,
        decoded,
    )
    return VttObjectResult(key=decoded, status="applied", session_id=row.id)
