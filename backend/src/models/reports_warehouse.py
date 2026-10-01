"""CPR-10 reports warehouse — Postgres schema ``reports`` (Technical Solution §4).

Tables only. No ingest, packet, or API behavior. Distinct from
``public.clips``, thin ``public.report_templates``, and CPR-13 ``export_*``.
``poll_responses`` is intentionally absent.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

_SCHEMA = "reports"


def _ts(*, nullable: bool = True) -> Mapped[datetime | None]:
    return mapped_column(DateTime(timezone=True), nullable=nullable)


class ReportsCampaignGroup(Base):
    __tablename__ = "campaign_groups"
    __table_args__ = (
        UniqueConstraint("name", name="uix_campaign_groups_name"),
        {"schema": _SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    client: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ReportsProgram(Base):
    __tablename__ = "programs"
    __table_args__ = {"schema": _SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="active"
    )
    platform_tool_program_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ReportsSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint(
            "zoom_meeting_uuid", name="uix_sessions_zoom_meeting_uuid"
        ),
        {"schema": _SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    program_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("reports.programs.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    zoom_meeting_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    zoom_meeting_uuid: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_date: Mapped[datetime | None] = _ts()
    transcript_s3_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ReportsClip(Base):
    __tablename__ = "clips"
    __table_args__ = (
        UniqueConstraint("youtube_video_id", name="uix_clips_youtube_video_id"),
        {"schema": _SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    program_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("reports.programs.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("reports.sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    youtube_video_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = _ts()
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ReportsSurveyResponse(Base):
    __tablename__ = "survey_responses"
    __table_args__ = {"schema": _SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("reports.sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    respondent_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="native")
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    cohort: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReportsQaEntry(Base):
    __tablename__ = "qa_entries"
    __table_args__ = {"schema": _SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("reports.sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    asker_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    answered: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    asked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    themes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    tagged_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    tagged_at: Mapped[datetime | None] = _ts()
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ReportsAttendance(Base):
    __tablename__ = "attendance"
    __table_args__ = {"schema": _SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("reports.sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    attendee_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    attendee_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    joined_at: Mapped[datetime | None] = _ts()
    left_at: Mapped[datetime | None] = _ts()
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReportsClipAnalytic(Base):
    __tablename__ = "clip_analytics"
    __table_args__ = (
        UniqueConstraint(
            "clip_id",
            "channel",
            "metric_date",
            name="uix_clip_analytics_clip_channel_date",
        ),
        {"schema": _SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clip_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("reports.clips.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    impressions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engaged_views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retention_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    engagement_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ReportsCampaignAnalytic(Base):
    __tablename__ = "campaign_analytics"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "channel",
            "metric_date",
            name="uix_campaign_analytics_campaign_channel_date",
        ),
        {"schema": _SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)
    reach: Mapped[int | None] = mapped_column(Integer, nullable=True)
    impressions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engaged: Mapped[int | None] = mapped_column(Integer, nullable=True)
    demographic: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ReportsMarketEvent(Base):
    __tablename__ = "market_events"
    __table_args__ = (
        UniqueConstraint("name", "event_date", name="uix_market_events_name_date"),
        {"schema": _SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ReportsCampaignMarketEvent(Base):
    __tablename__ = "campaign_market_events"
    __table_args__ = (
        PrimaryKeyConstraint(
            "campaign_id",
            "market_event_id",
            name="pk_campaign_market_events",
        ),
        {"schema": _SCHEMA},
    )

    campaign_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    market_event_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("reports.market_events.id", ondelete="CASCADE"),
        nullable=False,
    )


class ReportsSponsorSov(Base):
    __tablename__ = "sponsor_sov"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "sponsor_name",
            name="uix_sponsor_sov_session_sponsor",
        ),
        {"schema": _SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("reports.sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    sponsor_name: Mapped[str] = mapped_column(Text, nullable=False)
    share_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReportsReportTemplate(Base):
    """Versioned generation template. Not ``public.report_templates``."""

    __tablename__ = "report_templates"
    __table_args__ = (
        UniqueConstraint(
            "template_type",
            "version",
            name="uix_report_templates_type_version",
        ),
        {"schema": _SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_type: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    docx_template_key: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReportsReport(Base):
    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint(
            "campaign_id IS NOT NULL OR campaign_group_id IS NOT NULL",
            name="ck_reports_campaign_or_group",
        ),
        {"schema": _SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("campaigns.id"), nullable=True
    )
    campaign_group_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("reports.campaign_groups.id"), nullable=True
    )
    template_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reports.report_templates.id"), nullable=False
    )
    template_version: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    generated_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    finish_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    s3_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_completeness: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    group_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    tokens_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_output: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = _ts()
    completed_at: Mapped[datetime | None] = _ts()


class ReportsIngestJob(Base):
    __tablename__ = "ingest_jobs"
    __table_args__ = {"schema": _SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    campaign_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("campaigns.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    triggered_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    rows_written: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rows_skipped: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = _ts()
    completed_at: Mapped[datetime | None] = _ts()
