"""Campaign & report models — Content Hub admin surface."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from db_types import StringArray


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    program_name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    client_sponsor: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    disease_state: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    treatment_topic: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    reporting_period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    reporting_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    platforms: Mapped[list[str]] = mapped_column(
        StringArray(), nullable=False, server_default="{}"
    )
    target_audience: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_regions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_institutions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    physician_speakers: Mapped[str] = mapped_column(Text, nullable=False, default="")
    landing_page_url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    hubspot_campaign_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    livestream_url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    hubspot_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    hubspot_raw_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    executive_report_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    report_type: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="analytics"
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="draft")
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    tags: Mapped[list[str]] = mapped_column(
        StringArray(), nullable=False, server_default="{}"
    )
    template_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("report_templates.id", ondelete="SET NULL"), nullable=True
    )
    ai_insights: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    platform_data: Mapped[list["CampaignPlatformData"]] = relationship(
        "CampaignPlatformData",
        back_populates="campaign",
        cascade="all, delete-orphan",
    )


class CampaignPlatformData(Base):
    """One row per (campaign, platform, fetch_date UTC). Same-day refreshes update in place."""

    __tablename__ = "campaign_platform_data"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "platform",
            "fetch_date",
            name="uix_campaign_platform_fetch_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    fetch_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="missing")
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rows: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="api")
    filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    campaign: Mapped[Campaign] = relationship("Campaign", back_populates="platform_data")


class PlatformSyncRun(Base):
    __tablename__ = "platform_sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class IntegrationSetting(Base):
    """Non-HubSpot platform connector credentials — HubSpot stays on CHT."""

    __tablename__ = "integration_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ReportTemplate(Base):
    __tablename__ = "report_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False, default="analytics")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
