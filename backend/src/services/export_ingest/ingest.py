"""Campaign-level Zoom export ingest orchestration (CPR-13).

Wires ``ExportClient`` → optional transcript store → ``ingest_packet``.
Used by the admin route and the ``platform_export_ingest`` sync Lambda.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings
from models.campaign import Campaign
from models.export_warehouse import ExportIngestRun
from services import campaigns as campaign_service
from services.export_ingest.client import ExportClient, ExportClientError
from services.export_ingest.client_fixture import FixtureExportClient
from services.export_ingest.client_http import build_http_export_client
from services.export_ingest.m2m_secrets import resolve_m2m_settings_fields
from services.export_ingest.normalize import rewrite_packet_hub_campaign_id
from services.export_ingest.transcript_s3 import (
    MemoryTranscriptStore,
    S3TranscriptStore,
    TranscriptStore,
)
from services.export_ingest.upsert import ingest_packet


class ExportIngestConfigError(RuntimeError):
    """Missing/invalid PLATFORM_EXPORT_* configuration."""


@dataclass(frozen=True)
class ExportIngestRuntime:
    client: ExportClient
    transcript_store: TranscriptStore | None = None


@dataclass
class CampaignIngestResult:
    campaign_id: int
    status: str
    sessions_upserted: int = 0
    attendance_upserted: int = 0
    surveys_upserted: int = 0
    error: str | None = None
    run_id: int | None = None


@dataclass
class BatchIngestResult:
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    results: list[CampaignIngestResult] = field(default_factory=list)


def resolve_export_ingest_runtime(
    settings: Settings,
    *,
    source: str = "http",
) -> ExportIngestRuntime:
    """Build client + optional transcript store from settings.

    ``source``:
    * ``http`` — live HTTP client (requires ``platform_export_base_url`` + M2M)
    * ``fixture`` — JSON fixtures under ``platform_export_fixture_dir``
    """
    normalized = (source or "http").strip().lower()
    if normalized == "fixture":
        directory = (settings.platform_export_fixture_dir or "").strip()
        if not directory:
            raise ExportIngestConfigError(
                "Fixture export ingest is not configured "
                "(set PLATFORM_EXPORT_FIXTURE_DIR)"
            )
        client: ExportClient = FixtureExportClient(directory=Path(directory))
    elif normalized == "http":
        base_url = (settings.platform_export_base_url or "").strip()
        if not base_url:
            raise ExportIngestConfigError(
                "Platform export HTTP client is not configured "
                "(set PLATFORM_EXPORT_BASE_URL)"
            )
        try:
            token_url, client_id, client_secret, scope = resolve_m2m_settings_fields(
                secret_arn=(settings.platform_export_m2m_secret_arn or "").strip(),
                token_url=settings.platform_export_token_url,
                client_id=settings.platform_export_client_id,
                client_secret=settings.platform_export_client_secret,
                scope=settings.platform_export_scope,
                region_name=settings.aws_region,
            )
        except RuntimeError as exc:
            raise ExportIngestConfigError(str(exc)) from exc
        if not (token_url and client_id and client_secret):
            raise ExportIngestConfigError(
                "Platform export M2M is not configured "
                "(set PLATFORM_EXPORT_M2M_SECRET_ARN or "
                "TOKEN_URL + CLIENT_ID + CLIENT_SECRET)"
            )
        client = build_http_export_client(
            base_url=base_url,
            mode=settings.platform_export_http_mode,
            token_url=token_url,
            client_id=client_id,
            client_secret=client_secret,
            export_scope=scope,
        )
    else:
        raise ExportIngestConfigError("source must be 'http' or 'fixture'")

    store: TranscriptStore | None = None
    bucket = (settings.platform_export_transcript_bucket or "").strip()
    if bucket:
        store = S3TranscriptStore(bucket, region_name=settings.aws_region)

    return ExportIngestRuntime(client=client, transcript_store=store)


def resolve_export_ingest_runtime_http(
    settings: Settings,
    *,
    source: str = "http",
) -> ExportIngestRuntime:
    """Same as ``resolve_export_ingest_runtime`` but maps config errors to HTTP 503/400."""
    try:
        return resolve_export_ingest_runtime(settings, source=source)
    except ExportIngestConfigError as exc:
        detail = str(exc)
        status = 400 if "source must be" in detail else 503
        raise HTTPException(status_code=status, detail=detail) from exc


async def ingest_campaign(
    db: AsyncSession,
    campaign_id: int,
    *,
    client: ExportClient,
    transcript_store: TranscriptStore | None = None,
    trigger: str = "manual",
    export_campaign_id: str | None = None,
) -> ExportIngestRun:
    """Fetch export packet and upsert into the warehouse for a Hub campaign.

    ``campaign_id`` is Hub ``campaigns.id`` (integer FK for warehouse rows).
    ``export_campaign_id`` is the platform ``Program.campaignId`` string used
    to call the live export API (e.g. ``AZ-25-01_LIV001``). When omitted,
    the Hub integer id is used (fixture path / numeric export ids).
    """
    await campaign_service._get_campaign_row(db, campaign_id)
    fetch_key: str | int = (
        export_campaign_id.strip()
        if export_campaign_id and export_campaign_id.strip()
        else campaign_id
    )
    try:
        packet = await client.fetch_campaign_packet(fetch_key)
    except ExportClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    packet = rewrite_packet_hub_campaign_id(packet, campaign_id)

    return await ingest_packet(
        db,
        packet,
        trigger=trigger,
        transcript_store=transcript_store,
    )


async def list_campaign_ids_for_ingest(
    db: AsyncSession,
    *,
    campaign_ids: list[int] | None = None,
    limit: int | None = None,
) -> list[int]:
    """Resolve which Hub campaigns to ingest (explicit list or all, newest first)."""
    if campaign_ids:
        ids = list(dict.fromkeys(int(x) for x in campaign_ids))
        if limit is not None:
            return ids[: int(limit)]
        return ids

    stmt = select(Campaign.id).order_by(Campaign.id.desc())
    if limit is not None:
        stmt = stmt.limit(int(limit))
    return list((await db.execute(stmt)).scalars().all())


async def ingest_campaigns_batch(
    db: AsyncSession,
    *,
    client: ExportClient,
    transcript_store: TranscriptStore | None = None,
    campaign_ids: list[int] | None = None,
    export_campaign_ids: dict[int, str] | None = None,
    limit: int | None = None,
    trigger: str = "schedule",
) -> BatchIngestResult:
    """Ingest one or many campaigns; continue on per-campaign failures.

    ``export_campaign_ids`` maps Hub ``campaigns.id`` → platform
    ``Program.campaignId`` string for live HTTP fetch.
    """
    ids = await list_campaign_ids_for_ingest(
        db, campaign_ids=campaign_ids, limit=limit
    )
    export_map = export_campaign_ids or {}
    batch = BatchIngestResult()

    for campaign_id in ids:
        batch.processed += 1
        try:
            run = await ingest_campaign(
                db,
                campaign_id,
                client=client,
                transcript_store=transcript_store,
                trigger=trigger,
                export_campaign_id=export_map.get(campaign_id),
            )
            batch.succeeded += 1
            batch.results.append(
                CampaignIngestResult(
                    campaign_id=campaign_id,
                    status=run.status,
                    sessions_upserted=run.sessions_upserted,
                    attendance_upserted=run.attendance_upserted,
                    surveys_upserted=run.surveys_upserted,
                    run_id=run.id,
                )
            )
        except Exception as exc:  # noqa: BLE001 — isolate per campaign
            batch.failed += 1
            detail = getattr(exc, "detail", None)
            message = detail if isinstance(detail, str) else str(exc)
            batch.results.append(
                CampaignIngestResult(
                    campaign_id=campaign_id,
                    status="error",
                    error=message,
                )
            )

    return batch


def memory_runtime_for_tests(
    *,
    client: ExportClient,
    transcript_objects: dict[str, str] | None = None,
) -> ExportIngestRuntime:
    """Helper for unit/API tests — avoids live HTTP/S3."""
    store = (
        MemoryTranscriptStore(transcript_objects)
        if transcript_objects is not None
        else None
    )
    return ExportIngestRuntime(client=client, transcript_store=store)
