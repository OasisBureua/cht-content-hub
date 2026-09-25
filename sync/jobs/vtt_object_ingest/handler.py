"""vtt_object_ingest — S3 ObjectCreated → export_sessions.transcript_text.

Direct S3 notification payload (not SQS). Platform-tool owns the bucket
notify + lambda:AddPermission. This handler only reads the object and
updates an existing linked warehouse row.

Skips (success, no insert): unlinked prefix, missing session, null campaignId.
GetObject failures raise so async retries then the async DLQ.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from shared.runtime import configure_logging, install_paths, run_async

log = logging.getLogger(__name__)


def _iter_s3_keys(event: dict | None) -> Iterable[str]:
    from services.export_ingest.vtt_object import decode_object_key

    if not event:
        return
    for record in event.get("Records") or []:
        obj = ((record.get("s3") or {}).get("object") or {})
        key = decode_object_key(str(obj.get("key") or ""))
        if key:
            yield key


async def _run(event: dict) -> dict[str, Any]:
    from config import get_settings
    from database import async_session_maker
    from services.export_ingest.transcript_s3 import S3TranscriptStore
    from services.export_ingest.vtt_object import apply_vtt_object

    get_settings.cache_clear()
    settings = get_settings()
    bucket = (settings.platform_export_transcript_bucket or "").strip()
    if not bucket:
        raise RuntimeError("PLATFORM_EXPORT_TRANSCRIPT_BUCKET is not set")

    store = S3TranscriptStore(bucket, region_name=settings.aws_region)
    results: list[dict[str, Any]] = []

    async with async_session_maker() as db:
        for key in _iter_s3_keys(event):
            applied = await apply_vtt_object(db, store, key)
            results.append(
                {
                    "key": applied.key,
                    "status": applied.status,
                    "sessionId": applied.session_id,
                }
            )
        await db.commit()

    return {
        "status": "ok",
        "job": "vtt_object_ingest",
        "processed": len(results),
        "results": results,
    }


def handler(event: dict, context) -> dict:
    install_paths()
    configure_logging()
    return run_async(_run(event or {}))
