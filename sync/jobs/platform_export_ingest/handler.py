"""platform_export_ingest — scheduled CPR-13 Zoom export pull into Hub Aurora.

Business logic lives in ``services.export_ingest``. This handler only:
loads secrets, resolves the export client, and runs ``ingest_campaigns_batch``.

Event payload (optional)::

    {
      "campaignIds": [1, 2],
      "exportCampaignIds": {"1": "AZ-25-01_LIV001"},
      "limit": 50,
      "source": "http"
    }

Enable via Terraform ``sync_jobs_enabled.platform_export_ingest = true`` once
M2M + export are provisioned. Keep disabled until live smoke succeeds.
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


def _export_campaign_map(event: dict) -> dict[int, str] | None:
    raw = event.get("exportCampaignIds") or event.get("export_campaign_ids")
    if not raw or not isinstance(raw, dict):
        return None
    out: dict[int, str] = {}
    for key, value in raw.items():
        try:
            out[int(key)] = str(value).strip()
        except (TypeError, ValueError):
            continue
    return out or None


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
    export_map = _export_campaign_map(event)

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
            export_campaign_ids=export_map,
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
