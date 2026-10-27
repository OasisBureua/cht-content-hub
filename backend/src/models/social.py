"""Post → campaign links and daily post metrics (CPR-15).

Every social post the Hub knows is a ``posts`` row. A post counts toward a
campaign's reports through an active ``post_campaign_links`` row, and its
numbers live in ``post_metrics_daily``, one row per post, day and source.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

# How a link was made. Automatic links never replace or revive a manual one.
LINK_MANUAL = "manual"
LINK_CAMPAIGN_MAP = "campaign_map"
LINK_CONTENT_ID = "content_id"
LINK_WORDPRESS_EMBED = "wordpress_embed"
LINK_SHOOT = "shoot"
LINK_PROMOTED_POST = "promoted_post"
LINK_HUBSPOT_CAMPAIGN = "hubspot_campaign"  # CPR-56: HubSpot campaign GUID map

LINK_ACTIVE = "active"
LINK_SUGGESTED = "suggested"
LINK_REMOVED = "removed"

# post_metrics_daily.basis: per-day numbers, or lifetime totals as of that day.
BASIS_DAILY = "daily"
BASIS_LIFETIME = "lifetime_snapshot"


class PostCampaignLink(Base):
    __tablename__ = "post_campaign_links"
    __table_args__ = (
        UniqueConstraint("post_id", "campaign_id", name="uix_post_campaign_links_post_campaign"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("posts.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Platform Program.id, when the campaign has a single program.
    platform_program_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chm_content_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=LINK_ACTIVE, server_default=LINK_ACTIVE
    )
    created_by: Mapped[str] = mapped_column(
        String(255), nullable=False, default="system", server_default="system"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    removed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class PostMetricDaily(Base):
    __tablename__ = "post_metrics_daily"
    __table_args__ = (
        UniqueConstraint(
            "post_id", "metric_date", "source", name="uix_post_metrics_daily_post_date_source"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("posts.id", ondelete="CASCADE"), nullable=False
    )
    metric_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    basis: Mapped[str] = mapped_column(String(20), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
