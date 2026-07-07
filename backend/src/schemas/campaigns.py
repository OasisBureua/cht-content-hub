"""Campaign & report admin API schemas (CHT Content Hub UI contract)."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _to_camel(string: str) -> str:
    parts = string.split("_")
    return parts[0] + "".join(word.capitalize() for word in parts[1:])


class ApiModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=_to_camel,
        from_attributes=True,
    )


class Platform(StrEnum):
    LINKEDIN = "linkedin"
    META = "meta"
    YOUTUBE = "youtube"
    LIVESTREAM = "livestream"
    SURVEY = "survey"


class PlatformSyncStatus(StrEnum):
    MISSING = "missing"
    SYNCING = "syncing"
    AVAILABLE = "available"
    ERROR = "error"


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    DATA_NEEDED = "data_needed"
    READY_FOR_REVIEW = "ready_for_review"
    FINAL = "final"


class ReportType(StrEnum):
    ANALYTICS = "analytics"
    EXECUTIVE = "executive"


class CampaignOut(ApiModel):
    id: int
    name: str
    program_name: str = ""
    client_sponsor: str = ""
    disease_state: str = ""
    treatment_topic: str = ""
    reporting_period_start: date | None = None
    reporting_period_end: date | None = None
    platforms: list[str] = Field(default_factory=list)
    target_audience: str = ""
    target_regions: str = ""
    target_institutions: str = ""
    physician_speakers: str = ""
    landing_page_url: str = ""
    hubspot_campaign_id: str = ""
    event_date: date | None = None
    livestream_url: str = ""
    hubspot_synced_at: datetime | None = None
    hubspot_raw_data: Any | None = None
    executive_report_data: dict[str, Any] | None = None
    report_type: ReportType = ReportType.ANALYTICS
    status: CampaignStatus = CampaignStatus.DRAFT
    created_by: str = ""
    tags: list[str] = Field(default_factory=list)
    template_id: int | None = None
    created_at: datetime
    updated_at: datetime
    ai_insights: str | None = None


class CampaignListOut(ApiModel):
    items: list[CampaignOut]
    total: int


class CampaignCreate(ApiModel):
    name: str | None = None
    program_name: str | None = None
    client_sponsor: str | None = None
    disease_state: str | None = None
    treatment_topic: str | None = None
    reporting_period_start: date | None = None
    reporting_period_end: date | None = None
    platforms: list[str] | None = None
    target_audience: str | None = None
    target_regions: str | None = None
    target_institutions: str | None = None
    physician_speakers: str | None = None
    landing_page_url: str | None = None
    hubspot_campaign_id: str | None = None
    event_date: date | None = None
    livestream_url: str | None = None
    report_type: ReportType | None = None
    status: CampaignStatus | None = None
    created_by: str | None = None
    tags: list[str] | None = None
    template_id: int | None = None
    executive_report_data: dict[str, Any] | None = None
    hubspot_synced_at: datetime | None = None
    hubspot_raw_data: Any | None = None
    ai_insights: str | None = None


class CampaignUpdate(CampaignCreate):
    pass


class CsvUploadOut(ApiModel):
    id: int
    campaign_id: int
    platform: Platform
    filename: str
    row_count: int
    fetch_date: date | None = None
    synced_at: datetime | None = None
    uploaded_at: datetime | None = None


class CsvUploadListOut(ApiModel):
    items: list[CsvUploadOut]


class CsvUploadCreate(ApiModel):
    platform: Platform
    filename: str
    content: str


class PlatformSnapshotOut(ApiModel):
    campaign_id: int
    platform: str
    fetch_date: date | None = None
    status: PlatformSyncStatus
    synced_at: datetime | None = None
    next_sync_at: datetime | None = None
    row_count: int | None = None
    source: str | None = None
    error: str | None = None


class PlatformDataListOut(ApiModel):
    items: list[PlatformSnapshotOut]


class PlatformSyncResultOut(ApiModel):
    platform: str
    fetch_date: date | None = None
    status: PlatformSyncStatus
    synced_at: datetime | None = None
    row_count: int | None = None


class PlatformSyncAllOut(ApiModel):
    items: list[PlatformSyncResultOut]


class IntegrationPlatformOut(ApiModel):
    configured: bool = False
    enabled: bool = False
    note: str = ""
    last_tested_at: str | None = Field(default=None, alias="lastTestedAt")


class IntegrationsOut(ApiModel):
    platforms: dict[str, dict[str, Any]]


class IntegrationPatchIn(ApiModel):
    platforms: dict[str, dict[str, Any]]


class DataSourceSummaryOut(ApiModel):
    source: str
    status: str
    metrics_available: list[str] = Field(default_factory=list)
    metrics_missing: list[str] = Field(default_factory=list)
    last_updated: datetime | None = None


class DataValidationOut(ApiModel):
    hubspot_connected: bool
    hubspot_synced_at: datetime | None = None
    data_sources_summary: list[DataSourceSummaryOut] = Field(default_factory=list)


class InsightsOut(ApiModel):
    insights: str


class KpiTileOut(ApiModel):
    label: str
    value: str
    source: str
    note: str


class GlossaryEntryOut(ApiModel):
    term: str
    definition: str
    platform: str


class AnalyticsReportSectionsOut(ApiModel):
    executive_summary: str = ""
    cross_channel_snapshot: dict[str, Any] = Field(default_factory=lambda: {"rows": []})
    kpi_tiles: list[KpiTileOut] = Field(default_factory=list)
    hubspot_overview: Any | None = None
    landing_page_analytics: dict[str, Any] = Field(
        default_factory=lambda: {"source": "HubSpot", "available": False, "note": ""}
    )
    hcp_engagement: dict[str, Any] = Field(
        default_factory=lambda: {"source": "HubSpot", "available": False, "note": ""}
    )
    funnel_conversion: dict[str, Any] = Field(
        default_factory=lambda: {"available": False, "note": ""}
    )
    email_performance: dict[str, Any] = Field(
        default_factory=lambda: {"available": False, "note": ""}
    )
    linkedin_data: Any | None = None
    meta_data: Any | None = None
    youtube_data: Any | None = None
    livestream_data: Any | None = None
    survey_data: Any | None = None
    top_content: list[Any] = Field(default_factory=list)
    key_highlights: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    glossary: list[GlossaryEntryOut] = Field(default_factory=list)
    ai_insights: str | None = None


class AnalyticsReportOut(ApiModel):
    campaign: CampaignOut
    generated_at: datetime
    hubspot_data: Any | None = None
    csv_data: list[Any] = Field(default_factory=list)
    sections: AnalyticsReportSectionsOut
    data_validation: DataValidationOut


class ExecutivePlatformBreakdownOut(ApiModel):
    platform: str
    total_views: int
    total_impressions: int
    has_data: bool


class ExecutiveKeyLearningOut(ApiModel):
    title: str
    body: str


class ExecutiveReportConfigOut(ApiModel):
    overview_text: str = ""
    production_overview: str = ""
    distribution_overview: str = ""
    conclusion_text: str = ""
    targeting_narrative: str = ""
    content_themes: list[str] = Field(default_factory=list)
    pre_record_date: str = ""
    live_stream_date: str = ""
    distribution_date: str = ""
    long_form_episodes: str = ""
    short_form_topics: str = ""
    clip_variations: str = ""
    long_form_posts: str | None = None
    short_form_posts: str | None = None
    clip_posts: str | None = None
    key_learnings: list[ExecutiveKeyLearningOut] = Field(default_factory=list)


class ExecutiveReportOut(ApiModel):
    campaign: CampaignOut
    metrics: dict[str, Any]
    platform_breakdown: list[ExecutivePlatformBreakdownOut] = Field(default_factory=list)
    config: ExecutiveReportConfigOut


class TemplateOut(ApiModel):
    id: int
    name: str
    type: str
    description: str
    created_at: datetime
    updated_at: datetime


class TemplateListOut(ApiModel):
    items: list[TemplateOut]


class TemplateCreate(ApiModel):
    name: str
    type: str
    description: str = ""
