"""Campaign validation, reports, and AI insights.

Reports read stored platform snapshots + hubspot_raw_data on the campaign.
CHT orchestrates: pull from Hub at report time, POST .../report/generate here.
HubSpot is never called from Content Hub.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from models.campaign import CampaignPlatformData
from schemas.campaigns import (
    AnalyticsReportOut,
    AnalyticsReportSectionsOut,
    CampaignOut,
    DataSourceSummaryOut,
    DataValidationOut,
    ExecutivePlatformBreakdownOut,
    ExecutiveReportConfigOut,
    ExecutiveReportOut,
    InsightsOut,
    Platform,
)
from services import campaigns as campaign_service
from services import platform_data


def _hubspot_from_campaign(campaign_row) -> tuple[Any | None, bool, datetime | None]:
    data = campaign_row.hubspot_raw_data
    connected = bool(data)
    return data, connected, campaign_row.hubspot_synced_at


def _metrics_from_row(row: CampaignPlatformData | None) -> tuple[list[str], list[str]]:
    if row is None or row.status != "available" or not row.rows:
        return [], ["rows"]
    headers: set[str] = set()
    for item in row.rows[:5]:
        headers.update(str(k).lower() for k in item.keys())
    available = sorted(headers) if headers else ["rows"]
    return available, []


async def build_data_validation(db: AsyncSession, campaign_id: int) -> DataValidationOut:
    campaign = await campaign_service._get_campaign_row(db, campaign_id)
    hubspot_data, hubspot_connected, hubspot_synced_at = _hubspot_from_campaign(campaign)
    latest = await platform_data.latest_by_platform(db, campaign_id)
    summaries: list[DataSourceSummaryOut] = []

    summaries.append(
        DataSourceSummaryOut(
            source="HubSpot",
            status="available" if hubspot_data else "missing",
            metrics_available=["sessions", "pageviews"] if hubspot_data else [],
            metrics_missing=[] if hubspot_data else ["sessions", "pageviews"],
            last_updated=hubspot_synced_at,
        )
    )

    for platform in Platform:
        label = platform_data.platform_label(platform)
        row = latest.get(platform.value)
        metrics_available, metrics_missing = _metrics_from_row(row)
        summaries.append(
            DataSourceSummaryOut(
                source=label,
                status="available"
                if row and row.status == "available"
                else "missing",
                metrics_available=metrics_available,
                metrics_missing=metrics_missing,
                last_updated=row.synced_at if row else None,
            )
        )

    return DataValidationOut(
        hubspot_connected=hubspot_connected,
        hubspot_synced_at=hubspot_synced_at,
        data_sources_summary=summaries,
    )


async def generate_ai_insights(db: AsyncSession, campaign_id: int) -> InsightsOut:
    campaign = await campaign_service._get_campaign_row(db, campaign_id)
    hubspot_data, _, _ = _hubspot_from_campaign(campaign)
    snapshot_count = await campaign_service.count_snapshots_with_data(db, campaign_id)
    if snapshot_count == 0 and not hubspot_data:
        raise HTTPException(
            status_code=400,
            detail="Sync platform data or HubSpot snapshot before generating insights",
        )

    insights = (
        f"Placeholder insights for campaign '{campaign.name}'. "
        f"Platform snapshots: {snapshot_count}, "
        f"HubSpot={'yes' if hubspot_data else 'no'}."
    )
    campaign.ai_insights = insights
    campaign.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return InsightsOut(insights=insights)


async def build_analytics_report(db: AsyncSession, campaign_id: int) -> AnalyticsReportOut:
    campaign_out = await campaign_service.get_campaign(db, campaign_id)
    campaign_row = await campaign_service._get_campaign_row(db, campaign_id)
    hubspot_data, _, _ = _hubspot_from_campaign(campaign_row)
    validation = await build_data_validation(db, campaign_id)
    latest = await platform_data.latest_by_platform(db, campaign_id)

    csv_data = [
        {
            "platform": platform,
            "filename": row.filename,
            "fetchDate": row.fetch_date.isoformat(),
            "rowCount": row.row_count,
            "rows": row.rows,
            "syncedAt": row.synced_at.isoformat() if row.synced_at else None,
            "status": row.status,
            "source": row.source,
        }
        for platform, row in latest.items()
    ]

    def _platform_section(key: str) -> Any | None:
        row = latest.get(key)
        if row is None or row.status != "available":
            return None
        return {
            "rows": row.rows,
            "rowCount": row.row_count,
            "syncedAt": row.synced_at,
            "fetchDate": row.fetch_date.isoformat(),
        }

    sections = AnalyticsReportSectionsOut(
        executive_summary=f"Analytics report for {campaign_out.name} (stored platform data).",
        key_highlights=[
            "Reports reflect data synced or uploaded to Content Hub.",
            "Run platform sync or HubSpot sync before generating if data is stale.",
        ],
        recommendations=["Port report builder logic from CHT reports.ts."],
        hubspot_overview=hubspot_data,
        landing_page_analytics={
            "source": "HubSpot",
            "available": bool(hubspot_data),
            "note": "" if hubspot_data else "Awaiting CHT HubSpot sync",
        },
        linkedin_data=_platform_section(Platform.LINKEDIN.value),
        meta_data=_platform_section(Platform.META.value),
        youtube_data=_platform_section(Platform.YOUTUBE.value),
        livestream_data=_platform_section(Platform.LIVESTREAM.value),
        survey_data=_platform_section(Platform.SURVEY.value),
        data_gaps=[
            s.source
            for s in validation.data_sources_summary
            if s.status == "missing"
        ],
        ai_insights=campaign_out.ai_insights,
    )

    return AnalyticsReportOut(
        campaign=campaign_out,
        generated_at=datetime.now(timezone.utc),
        hubspot_data=hubspot_data,
        csv_data=csv_data,
        sections=sections,
        data_validation=validation,
    )


async def build_executive_report(db: AsyncSession, campaign_id: int) -> ExecutiveReportOut:
    campaign_out = await campaign_service.get_campaign(db, campaign_id)
    stored = campaign_out.executive_report_data or {}
    latest = await platform_data.latest_by_platform(db, campaign_id)

    config = ExecutiveReportConfigOut(
        overview_text=str(stored.get("overviewText", "")),
        production_overview=str(stored.get("productionOverview", "")),
        distribution_overview=str(stored.get("distributionOverview", "")),
        conclusion_text=str(stored.get("conclusionText", "")),
        targeting_narrative=str(stored.get("targetingNarrative", "")),
        content_themes=list(stored.get("contentThemes", [])),
        pre_record_date=str(stored.get("preRecordDate", "")),
        live_stream_date=str(stored.get("liveStreamDate", "")),
        distribution_date=str(stored.get("distributionDate", "")),
        long_form_episodes=str(stored.get("longFormEpisodes", "")),
        short_form_topics=str(stored.get("shortFormTopics", "")),
        clip_variations=str(stored.get("clipVariations", "")),
        long_form_posts=stored.get("longFormPosts"),
        short_form_posts=stored.get("shortFormPosts"),
        clip_posts=stored.get("clipPosts"),
        key_learnings=stored.get("keyLearnings", []),
    )

    platform_breakdown = [
        ExecutivePlatformBreakdownOut(
            platform=p.value,
            total_views=0,
            total_impressions=0,
            has_data=(
                p.value in latest and latest[p.value].status == "available"
            ),
        )
        for p in Platform
        if p.value in campaign_out.platforms
    ]

    return ExecutiveReportOut(
        campaign=campaign_out,
        metrics={
            "totalViews": None,
            "totalImpressions": None,
            "totalViewsFormatted": None,
            "totalImpressionsFormatted": None,
            "youtube": None,
            "linkedin": None,
            "meta": None,
            "livestream": None,
            "survey": None,
        },
        platform_breakdown=platform_breakdown,
        config=config,
    )
