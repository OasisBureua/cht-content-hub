"""Campaign CRUD and CSV upload (CSV ingests into campaign_platform_data)."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.campaign import Campaign, CampaignPlatformData
from schemas.campaigns import (
    CampaignCreate,
    CampaignOut,
    CampaignStatus,
    CampaignUpdate,
    CsvUploadCreate,
    CsvUploadOut,
    Platform,
    ReportType,
)
from services import platform_data


def _campaign_to_out(campaign: Campaign) -> CampaignOut:
    return CampaignOut.model_validate(campaign)


async def list_campaigns(
    db: AsyncSession, *, q: str | None = None
) -> tuple[list[CampaignOut], int]:
    stmt = select(Campaign).order_by(Campaign.created_at.desc())
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Campaign.name.ilike(like),
                Campaign.client_sponsor.ilike(like),
                Campaign.program_name.ilike(like),
            )
        )
    rows = list((await db.execute(stmt)).scalars().all())
    return [_campaign_to_out(c) for c in rows], len(rows)


async def get_campaign(db: AsyncSession, campaign_id: int) -> CampaignOut:
    campaign = await db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return _campaign_to_out(campaign)


async def _get_campaign_row(db: AsyncSession, campaign_id: int) -> Campaign:
    campaign = await db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


async def create_campaign(db: AsyncSession, payload: CampaignCreate) -> CampaignOut:
    data = payload.model_dump(exclude_unset=True)
    if not data.get("name"):
        data["name"] = "Untitled campaign"

    status = data.pop("status", CampaignStatus.DRAFT)
    report_type = data.pop("report_type", ReportType.ANALYTICS)
    if hasattr(status, "value"):
        status = status.value
    if hasattr(report_type, "value"):
        report_type = report_type.value

    campaign = Campaign(status=status, report_type=report_type, **data)
    db.add(campaign)
    await db.flush()
    await db.refresh(campaign)
    return _campaign_to_out(campaign)


async def update_campaign(
    db: AsyncSession, campaign_id: int, payload: CampaignUpdate
) -> CampaignOut:
    campaign = await _get_campaign_row(db, campaign_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if hasattr(value, "value"):
            value = value.value
        setattr(campaign, key, value)
    campaign.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(campaign)
    return _campaign_to_out(campaign)


async def delete_campaign(db: AsyncSession, campaign_id: int) -> None:
    campaign = await _get_campaign_row(db, campaign_id)
    await db.delete(campaign)
    await db.flush()


def _platform_data_to_csv_out(row: CampaignPlatformData) -> CsvUploadOut:
    synced = row.synced_at or row.updated_at
    return CsvUploadOut(
        id=row.id,
        campaign_id=row.campaign_id,
        platform=Platform(row.platform),
        filename=row.filename or "",
        row_count=row.row_count or 0,
        fetch_date=row.fetch_date,
        synced_at=synced,
        uploaded_at=synced,
    )


async def list_uploads(db: AsyncSession, campaign_id: int) -> list[CsvUploadOut]:
    """Latest CSV-sourced platform data per platform (bootstrap API)."""
    await _get_campaign_row(db, campaign_id)
    latest = await platform_data.latest_by_platform(db, campaign_id)
    return [
        _platform_data_to_csv_out(row)
        for row in latest.values()
        if row.source == "csv" and row.filename
    ]


def _parse_csv(content: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV must include a header row")
    return [dict(row) for row in reader]


async def upload_csv(
    db: AsyncSession,
    campaign_id: int,
    payload: CsvUploadCreate,
) -> CsvUploadOut:
    campaign = await _get_campaign_row(db, campaign_id)
    rows = _parse_csv(payload.content)
    platform = payload.platform.value

    record = await platform_data.upsert_platform_data(
        db,
        campaign_id=campaign_id,
        platform=platform,
        rows=rows,
        source="csv",
        filename=payload.filename,
        raw={"filename": payload.filename, "source": "csv_upload"},
        trigger="csv_upload",
    )

    if platform not in campaign.platforms:
        campaign.platforms = [*campaign.platforms, platform]

    campaign.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(record)
    return _platform_data_to_csv_out(record)


async def count_snapshots_with_data(db: AsyncSession, campaign_id: int) -> int:
    latest = await platform_data.latest_by_platform(db, campaign_id)
    return sum(1 for row in latest.values() if row.status == "available" and row.row_count)
