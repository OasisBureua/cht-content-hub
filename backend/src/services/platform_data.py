"""Consolidated platform data — daily UTC buckets, same-day upsert."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.campaign import (
    Campaign,
    CampaignPlatformData,
    IntegrationSetting,
    PlatformSyncRun,
)
from schemas.campaigns import (
    Platform,
    PlatformDataListOut,
    PlatformSnapshotOut,
    PlatformSyncResultOut,
    PlatformSyncStatus,
)

_PLATFORM_LABELS = {
    Platform.LINKEDIN: "LinkedIn",
    Platform.META: "Meta",
    Platform.YOUTUBE: "YouTube",
    Platform.LIVESTREAM: "Livestream",
    Platform.SURVEY: "Survey",
}

_DAILY_SYNC_HOUR_UTC = 6


def utc_fetch_date(when: datetime | None = None) -> date:
    when = when or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).date()


def _default_next_sync_at(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    tomorrow = utc_fetch_date(now) + timedelta(days=1)
    return datetime(
        tomorrow.year,
        tomorrow.month,
        tomorrow.day,
        _DAILY_SYNC_HOUR_UTC,
        0,
        0,
        tzinfo=timezone.utc,
    )


async def _get_campaign_row(db: AsyncSession, campaign_id: int) -> Campaign:
    campaign = await db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


async def _all_rows_for_campaign(
    db: AsyncSession, campaign_id: int
) -> list[CampaignPlatformData]:
    return list(
        (
            await db.execute(
                select(CampaignPlatformData)
                .where(CampaignPlatformData.campaign_id == campaign_id)
                .order_by(
                    CampaignPlatformData.platform,
                    CampaignPlatformData.fetch_date.desc(),
                    CampaignPlatformData.synced_at.desc(),
                )
            )
        ).scalars()
    )


async def latest_by_platform(
    db: AsyncSession, campaign_id: int
) -> dict[str, CampaignPlatformData]:
    """Most recent fetch_date (then synced_at) per platform."""
    latest: dict[str, CampaignPlatformData] = {}
    for row in await _all_rows_for_campaign(db, campaign_id):
        if row.platform not in latest:
            latest[row.platform] = row
    return latest


def _row_to_out(row: CampaignPlatformData | None, *, campaign_id: int, platform: str) -> PlatformSnapshotOut:
    if row is None:
        return PlatformSnapshotOut(
            campaign_id=campaign_id,
            platform=platform,
            fetch_date=None,
            status=PlatformSyncStatus.MISSING,
            synced_at=None,
            next_sync_at=None,
            row_count=None,
            source=None,
            error=None,
        )
    return PlatformSnapshotOut(
        campaign_id=row.campaign_id,
        platform=row.platform,
        fetch_date=row.fetch_date,
        status=PlatformSyncStatus(row.status),
        synced_at=row.synced_at,
        next_sync_at=row.next_sync_at,
        row_count=row.row_count,
        source=row.source,
        error=row.error,
    )


async def _log_sync_run(
    db: AsyncSession,
    *,
    campaign_id: int,
    platform: str,
    trigger: str,
    started_at: datetime,
    status: str,
    finished_at: datetime | None = None,
    error: str | None = None,
) -> None:
    db.add(
        PlatformSyncRun(
            campaign_id=campaign_id,
            platform=platform,
            trigger=trigger,
            started_at=started_at,
            finished_at=finished_at,
            status=status,
            error=error,
        )
    )


async def upsert_platform_data(
    db: AsyncSession,
    *,
    campaign_id: int,
    platform: str,
    rows: list[dict[str, str | Any]],
    source: str,
    trigger: str,
    filename: str | None = None,
    raw: dict | None = None,
    when: datetime | None = None,
) -> CampaignPlatformData:
    """Upsert today's UTC bucket; new calendar day inserts a new row."""
    now = when or datetime.now(timezone.utc)
    fetch_day = utc_fetch_date(now)
    normalized = [dict(row) for row in rows]

    existing = (
        await db.execute(
            select(CampaignPlatformData).where(
                CampaignPlatformData.campaign_id == campaign_id,
                CampaignPlatformData.platform == platform,
                CampaignPlatformData.fetch_date == fetch_day,
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.status = PlatformSyncStatus.AVAILABLE.value
        existing.synced_at = now
        existing.next_sync_at = _default_next_sync_at(now)
        existing.row_count = len(normalized)
        existing.rows = normalized
        existing.raw = raw
        existing.source = source
        if filename is not None:
            existing.filename = filename
        existing.error = None
        existing.updated_at = now
        record = existing
    else:
        record = CampaignPlatformData(
            campaign_id=campaign_id,
            platform=platform,
            fetch_date=fetch_day,
            status=PlatformSyncStatus.AVAILABLE.value,
            synced_at=now,
            next_sync_at=_default_next_sync_at(now),
            row_count=len(normalized),
            rows=normalized,
            raw=raw,
            source=source,
            filename=filename,
        )
        db.add(record)

    await _log_sync_run(
        db,
        campaign_id=campaign_id,
        platform=platform,
        trigger=trigger,
        started_at=now,
        finished_at=now,
        status="success",
    )
    await db.flush()
    await db.refresh(record)
    return record


async def list_platform_data(db: AsyncSession, campaign_id: int) -> PlatformDataListOut:
    campaign = await _get_campaign_row(db, campaign_id)
    latest = await latest_by_platform(db, campaign_id)
    items = [
        _row_to_out(latest.get(platform_value), campaign_id=campaign_id, platform=platform_value)
        for platform_value in campaign.platforms
    ]
    return PlatformDataListOut(items=items)


async def _integration_config(db: AsyncSession, platform: str) -> dict | None:
    row = await db.get(IntegrationSetting, platform)
    if row is None:
        return None
    return row.value_json


async def sync_platform(
    db: AsyncSession,
    campaign_id: int,
    platform: str,
    *,
    trigger: str = "manual",
) -> PlatformSyncResultOut:
    campaign = await _get_campaign_row(db, campaign_id)
    if platform not in campaign.platforms:
        raise HTTPException(
            status_code=400,
            detail=f"Platform {platform} is not enabled on this campaign",
        )

    started = datetime.now(timezone.utc)
    config = await _integration_config(db, platform)
    if config is None:
        await _log_sync_run(
            db,
            campaign_id=campaign_id,
            platform=platform,
            trigger=trigger,
            started_at=started,
            finished_at=datetime.now(timezone.utc),
            status="error",
            error=f"{platform} connector not configured",
        )
        await db.flush()
        raise HTTPException(
            status_code=400,
            detail=f"{platform} connector not configured — upload CSV or configure integration",
        )

    if not config.get("stub") and not config.get("enabled"):
        await _log_sync_run(
            db,
            campaign_id=campaign_id,
            platform=platform,
            trigger=trigger,
            started_at=started,
            finished_at=datetime.now(timezone.utc),
            status="error",
            error=f"{platform} connector not enabled",
        )
        await db.flush()
        raise HTTPException(status_code=400, detail=f"{platform} connector not enabled")

    stub_rows = config.get("stubRows") or [
        {"impressions": "0", "clicks": "0", "source": "stub-sync"},
    ]
    record = await upsert_platform_data(
        db,
        campaign_id=campaign_id,
        platform=platform,
        rows=stub_rows,
        source="api",
        raw={"connector": platform, "stub": True},
        trigger=trigger,
    )
    campaign.updated_at = datetime.now(timezone.utc)
    await db.flush()

    return PlatformSyncResultOut(
        platform=platform,
        fetch_date=record.fetch_date,
        status=PlatformSyncStatus(record.status),
        synced_at=record.synced_at,
        row_count=record.row_count,
    )


async def sync_all_platforms(
    db: AsyncSession, campaign_id: int
) -> list[PlatformSyncResultOut]:
    campaign = await _get_campaign_row(db, campaign_id)
    results: list[PlatformSyncResultOut] = []
    errors: list[str] = []

    for platform_value in campaign.platforms:
        try:
            results.append(
                await sync_platform(db, campaign_id, platform_value, trigger="manual")
            )
        except HTTPException as exc:
            errors.append(f"{platform_value}: {exc.detail}")

    if not results and errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    return results


def platform_label(platform: Platform) -> str:
    return _PLATFORM_LABELS[platform]
