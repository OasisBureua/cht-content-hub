"""platform_export_ingest — scheduled CPR-13 Zoom export pull into Hub Aurora.

Business logic lives in ``services.export_ingest``. This handler only:
loads secrets, resolves the export client, and runs ``ingest_campaigns_batch``.

Event payload (optional)::

    {
      "campaignIds": [1, 2],   # omit = all campaigns (newest first)
      "limit": 50,             # optional cap
      "source": "http"         # or "fixture" when PLATFORM_EXPORT_FIXTURE_DIR set
    }

Enable via Terraform ``sync_jobs_enabled.platform_export_ingest = true`` once
CPR-12 M2M + export API (and optional transcript S3 IAM) are provisioned.
"""

from __future__ import annotations

import json
import logging

from shared.runtime import configure_logging, install_paths, run_async

log = logging.getLogger(__name__)


def _parse_event(event: dict | None) -> dict:
    if not event:
        return {}
    if "Records" in event and event["Records"]:
        body = event["Records"][0].get("body", "{}")
        try:
            return json.loads(body) if isinstance(body, str) else (body or {})
        except json.JSONDecodeError:
            return {}
    return event


async def _run(event: dict) -> dict:
    from config import get_settings
    from database import async_session_maker
    from services.export_ingest.ingest import (
        ExportIngestConfigError,
        ingest_campaigns_batch,
        resolve_export_ingest_runtime,
    )

    get_settings.cache_clear()
    settings = get_settings()
    source = str(event.get("source") or "http")
    campaign_ids = event.get("campaignIds") or event.get("campaign_ids")
    limit = event.get("limit")

    try:
        runtime = resolve_export_ingest_runtime(settings, source=source)
    except ExportIngestConfigError as exc:
        log.error("platform_export_ingest misconfigured: %s", exc)
        return {
            "status": "error",
            "job": "platform_export_ingest",
            "error": str(exc),
        }

    async with async_session_maker() as db:
        batch = await ingest_campaigns_batch(
            db,
            client=runtime.client,
            transcript_store=runtime.transcript_store,
            campaign_ids=list(campaign_ids) if campaign_ids else None,
            limit=int(limit) if limit is not None else None,
            trigger="schedule",
        )
        await db.commit()

    return {
        "status": "ok" if batch.failed == 0 else "partial",
        "job": "platform_export_ingest",
        "processed": batch.processed,
        "succeeded": batch.succeeded,
        "failed": batch.failed,
        "results": [
            {
                "campaignId": row.campaign_id,
                "status": row.status,
                "sessionsUpserted": row.sessions_upserted,
                "attendanceUpserted": row.attendance_upserted,
                "surveysUpserted": row.surveys_upserted,
                "error": row.error,
                "runId": row.run_id,
            }
            for row in batch.results
        ],
    }


def handler(event: dict, context) -> dict:
    install_paths()
    configure_logging()
    return run_async(_run(_parse_event(event)))
