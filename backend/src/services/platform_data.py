"""Consolidated platform data — daily UTC buckets, same-day upsert."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from config import get_settings
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
from services.connectors.common import integration_or_env
from services.connectors.linkedin_ads import mapped_linkedin_campaign_ids
from services.connectors.linkedin_auth import linkedin_ads_access_token
from services import post_links, social_posts
from services.connectors import (
    ConnectorError,
    ConnectorNoData,
    ConnectorNotMapped,
    fetch_linkedin_ads_metrics,
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


async def latest_by_platform(
    db: AsyncSession,
    campaign_id: int,
    *,
    window_start: date | None = None,
    window_end: date | None = None,
    with_rows: bool = True,
) -> dict[str, CampaignPlatformData]:
    """Most recent fetch_date (then synced_at) per platform.

    CPR-44: when a date window is set, only snapshots whose ``fetch_date``
    falls inside the window are considered; otherwise the global latest.
    ``with_rows=False`` skips loading the ``rows`` / ``raw`` JSON.

    CPR-15: YouTube comes from the campaign's linked posts
    (``social_posts.campaign_post_snapshots``). A stored row (CSV upload)
    is used instead only when its fetch_date is newer.
    """
    filters = [CampaignPlatformData.campaign_id == campaign_id]
    if window_start is not None:
        filters.append(CampaignPlatformData.fetch_date >= window_start)
    if window_end is not None:
        filters.append(CampaignPlatformData.fetch_date <= window_end)
    ranked = (
        select(
            CampaignPlatformData.id,
            func.row_number()
            .over(
                partition_by=CampaignPlatformData.platform,
                order_by=(
                    CampaignPlatformData.fetch_date.desc(),
                    CampaignPlatformData.synced_at.desc(),
                ),
            )
            .label("rank"),
        )
        .where(*filters)
        .subquery()
    )
    query = (
        select(CampaignPlatformData)
        .join(ranked, CampaignPlatformData.id == ranked.c.id)
        .where(ranked.c.rank == 1)
        .order_by(CampaignPlatformData.platform)
    )
    if not with_rows:
        query = query.options(
            defer(CampaignPlatformData.rows, raiseload=True),
            defer(CampaignPlatformData.raw, raiseload=True),
        )
    latest = {row.platform: row for row in (await db.execute(query)).scalars()}
    from_posts = await social_posts.campaign_post_snapshots(
        db, campaign_id, window_start=window_start, window_end=window_end
    )
    for platform, snapshot in from_posts.items():
        stored = latest.get(platform)
        if stored is None or stored.fetch_date <= snapshot.fetch_date:
            latest[platform] = snapshot
    return dict(sorted(latest.items()))


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
    campaign_id: int | None,
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
    latest = await latest_by_platform(db, campaign_id, with_rows=False)
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


async def _fetch_connector_rows(
    *,
    platform: str,
    campaign: Campaign,
    integration: dict[str, Any],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    settings = get_settings()

    if platform == Platform.LINKEDIN.value:
        # Unmapped campaigns stay unmapped even when the token is broken.
        mapped_linkedin_campaign_ids(integration, campaign.id)
        access_token, _ = await linkedin_ads_access_token(settings, integration)
        result = await fetch_linkedin_ads_metrics(
            access_token=access_token,
            ad_account_id=integration_or_env(
                integration,
                integration_key="adAccountId",
                env_value=settings.linkedin_ad_account_id,
            ),
            campaign_id=campaign.id,
            integration=integration,
            reporting_period_start=campaign.reporting_period_start,
            reporting_period_end=campaign.reporting_period_end,
            api_version=settings.linkedin_ads_api_version,
        )
        return result.rows, result.raw

    raise HTTPException(
        status_code=400,
        detail=f"API sync for {platform} is not implemented — upload CSV instead",
    )


SyncOutcomeStatus = Literal["ok", "unmapped", "no_data", "error", "not_enabled"]


@dataclass(frozen=True)
class SyncOutcome:
    """Result of one platform sync.

    ``status`` is also what the run log records, except ``ok`` is stored as
    ``success``.
    """

    status: SyncOutcomeStatus
    result: PlatformSyncResultOut | None = None
    detail: str | None = None


async def _log_failed_run(
    db: AsyncSession,
    *,
    campaign_id: int,
    platform: str,
    trigger: str,
    started: datetime,
    status: str,
    error: str,
) -> None:
    await _log_sync_run(
        db,
        campaign_id=campaign_id,
        platform=platform,
        trigger=trigger,
        started_at=started,
        finished_at=datetime.now(timezone.utc),
        status=status,
        error=error,
    )
    await db.flush()


async def _sync_linked_youtube(
    db: AsyncSession, campaign: Campaign, *, trigger: str, started: datetime
) -> SyncOutcome:
    """CPR-15: relink, refresh the campaign's linked videos, return today's snapshot.

    New uploads are found by the daily sync; this refreshes what is linked.
    """
    platform = Platform.YOUTUBE.value
    await post_links.relink(db)
    video_ids = await social_posts.linked_provider_ids(db, campaign.id, platform)
    if not video_ids:
        detail = f"No YouTube posts linked to campaign {campaign.id}"
        await _log_failed_run(
            db, campaign_id=campaign.id, platform=platform, trigger=trigger,
            started=started, status="unmapped", error=detail,
        )
        return SyncOutcome("unmapped", detail=detail)

    stats = await social_posts.sync_youtube(db, trigger=trigger, video_ids=video_ids, log_run=False)
    if stats.error or not stats.videos:
        status = "error" if stats.error else "no_data"
        detail = stats.error or (
            "None of the linked YouTube videos were returned (private, deleted, or wrong IDs)"
        )
        await _log_failed_run(
            db, campaign_id=campaign.id, platform=platform, trigger=trigger,
            started=started, status=status, error=detail,
        )
        return SyncOutcome(status, detail=detail)

    snapshot = (await social_posts.campaign_post_snapshots(db, campaign.id))[platform]
    await _log_sync_run(
        db,
        campaign_id=campaign.id,
        platform=platform,
        trigger=trigger,
        started_at=started,
        finished_at=datetime.now(timezone.utc),
        status="success",
    )
    campaign.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return SyncOutcome(
        "ok",
        result=PlatformSyncResultOut(
            platform=platform,
            fetch_date=snapshot.fetch_date,
            status=PlatformSyncStatus.AVAILABLE,
            synced_at=snapshot.synced_at,
            row_count=snapshot.row_count,
        ),
    )


async def run_platform_sync(
    db: AsyncSession,
    campaign: Campaign,
    platform: str,
    *,
    trigger: str,
) -> SyncOutcome:
    """Fetch and store one platform for one campaign; every attempt is logged.

    CPR-15: an unmapped campaign is ``unmapped`` and a mapped campaign with no
    activity is ``no_data``. Neither counts as an error.
    """
    started = datetime.now(timezone.utc)
    if platform == Platform.YOUTUBE.value:
        return await _sync_linked_youtube(db, campaign, trigger=trigger, started=started)
    config = await _integration_config(db, platform)
    if config is None or (not config.get("stub") and not config.get("enabled")):
        detail = (
            f"{platform} connector not configured"
            if config is None
            else f"{platform} connector not enabled"
        )
        await _log_failed_run(
            db,
            campaign_id=campaign.id,
            platform=platform,
            trigger=trigger,
            started=started,
            status="not_enabled",
            error=detail,
        )
        return SyncOutcome("not_enabled", detail=detail)

    if config.get("stub"):
        rows = config.get("stubRows") or [
            {"impressions": "0", "clicks": "0", "source": "stub-sync"},
        ]
        raw: dict[str, Any] = {"connector": platform, "stub": True}
    else:
        try:
            rows, raw = await _fetch_connector_rows(
                platform=platform,
                campaign=campaign,
                integration=config,
            )
        except ConnectorNotMapped as exc:
            await _log_failed_run(
                db,
                campaign_id=campaign.id,
                platform=platform,
                trigger=trigger,
                started=started,
                status="unmapped",
                error=str(exc),
            )
            return SyncOutcome("unmapped", detail=str(exc))
        except ConnectorNoData as exc:
            await _log_failed_run(
                db,
                campaign_id=campaign.id,
                platform=platform,
                trigger=trigger,
                started=started,
                status="no_data",
                error=str(exc),
            )
            return SyncOutcome("no_data", detail=str(exc))
        except ConnectorError as exc:
            await _log_failed_run(
                db,
                campaign_id=campaign.id,
                platform=platform,
                trigger=trigger,
                started=started,
                status="error",
                error=str(exc),
            )
            return SyncOutcome("error", detail=str(exc))

    record = await upsert_platform_data(
        db,
        campaign_id=campaign.id,
        platform=platform,
        rows=rows,
        source="api",
        raw=raw,
        trigger=trigger,
    )
    campaign.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return SyncOutcome(
        "ok",
        result=PlatformSyncResultOut(
            platform=platform,
            fetch_date=record.fetch_date,
            status=PlatformSyncStatus(record.status),
            synced_at=record.synced_at,
            row_count=record.row_count,
        ),
    )


_OUTCOME_HTTP_STATUS = {"not_enabled": 400, "unmapped": 400, "no_data": 404, "error": 502}


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

    outcome = await run_platform_sync(db, campaign, platform, trigger=trigger)
    if outcome.result is None:
        # get_db rolls back on the HTTPException; keep the failed run logged.
        await db.commit()
        raise HTTPException(
            status_code=_OUTCOME_HTTP_STATUS[outcome.status],
            detail=outcome.detail,
        )
    return outcome.result


async def latest_sync_runs(db: AsyncSession, campaign_id: int) -> dict[str, PlatformSyncRun]:
    """Most recent sync attempt per platform for a campaign."""
    ranked = (
        select(
            PlatformSyncRun.id,
            func.row_number()
            .over(
                partition_by=PlatformSyncRun.platform,
                order_by=(PlatformSyncRun.started_at.desc(), PlatformSyncRun.id.desc()),
            )
            .label("rank"),
        )
        .where(PlatformSyncRun.campaign_id == campaign_id)
        .subquery()
    )
    runs = (
        await db.execute(
            select(PlatformSyncRun)
            .join(ranked, PlatformSyncRun.id == ranked.c.id)
            .where(ranked.c.rank == 1)
        )
    ).scalars()
    return {run.platform: run for run in runs}


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
