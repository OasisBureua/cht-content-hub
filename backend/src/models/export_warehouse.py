"""CPR-13 Zoom export warehouse — Hub Aurora persistence for platform export.

Stores sessions, raw attendance events, optional survey stubs, and ingest
audit runs. Distinct from HCP-intel ``webinar_*`` tables and from
``Shoot.diarized_transcript`` (studio path used by report-packet v1).

Business keys:
* ``export_sessions.platform_tool_program_id`` — Platform ``Program.id`` (cuid)
* ``export_attendance_events.dedupe_key`` — stable upsert key (Phase C mapper)
* ``campaign_id`` — Hub ``campaigns.id`` when export includes it
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
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

if TYPE_CHECKING:
    from models.campaign import Campaign


class ExportSession(Base):
    """One Zoom-backed platform Program / session row."""

    __tablename__ = "export_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform_tool_program_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    campaign_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    session_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    zoom_meeting_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    zoom_uuid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    transcript_s3_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    transcript_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    zoom_session_ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    campaign: Mapped["Campaign | None"] = relationship("Campaign")
    attendance_events: Mapped[list["ExportAttendanceEvent"]] = relationship(
        "ExportAttendanceEvent",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ExportAttendanceEvent(Base):
    """Raw JOINED/LEFT (or report-import) attendance row from platform."""

    __tablename__ = "export_attendance_events"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uix_export_attendance_dedupe_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dedupe_key: Mapped[str] = mapped_column(String(512), nullable=False)
    platform_tool_program_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "export_sessions.platform_tool_program_id",
            ondelete="CASCADE",
            name="fk_export_attendance_program",
        ),
        nullable=False,
        index=True,
    )
    campaign_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    event: Mapped[str] = mapped_column(String(16), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    participant_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    participant_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    platform_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    zoom_participant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    zoom_meeting_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    join_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    leave_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    session: Mapped["ExportSession"] = relationship(
        "ExportSession",
        back_populates="attendance_events",
        foreign_keys=[platform_tool_program_id],
    )


class ExportSurveyResponse(Base):
    """CPR-14 stub table — typed storage; not required for CPR-13 sessions path."""

    __tablename__ = "export_survey_responses"
    __table_args__ = (
        UniqueConstraint(
            "dedupe_key", name="uix_export_survey_responses_dedupe_key"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dedupe_key: Mapped[str] = mapped_column(String(512), nullable=False)
    campaign_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    platform_tool_program_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    respondent_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    survey_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    submission_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ExportIngestRun(Base):
    """Audit row for one warehouse ingest attempt (fixture or live)."""

    __tablename__ = "export_ingest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    trigger: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    sessions_upserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attendance_upserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    surveys_upserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
