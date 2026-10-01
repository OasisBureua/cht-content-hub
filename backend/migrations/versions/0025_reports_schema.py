"""CPR-10: locked reports schema (Technical Solution §4).

Creates Postgres schema ``reports`` and the §4 warehouse tables.
Columns follow the CREATE TABLE blocks, not the section intro line that
says every table has version/updated_at (several tables omit those).

Out of this revision:
* ``poll_responses`` (CPR-10 ticket: add when REP-INT-003 lands)
* ``reports.campaigns`` (identity stays ``public.campaigns``)
* ``public.export_*``, ``public.clips``, thin ``public.report_templates``

Revision ID: 0025_reports_schema
Revises: 0024_report_template_pointer
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025_reports_schema"
down_revision: Union[str, None] = "0024_report_template_pointer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "reports"

_TABLES_DROP_ORDER = (
    "ingest_jobs",
    "reports",
    "report_templates",
    "sponsor_sov",
    "campaign_market_events",
    "market_events",
    "campaign_analytics",
    "clip_analytics",
    "attendance",
    "qa_entries",
    "survey_responses",
    "clips",
    "sessions",
    "programs",
    "campaign_groups",
)


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _table_exists(name: str) -> bool:
    return name in _inspector().get_table_names(schema=SCHEMA)


def _index_exists(table: str, index: str) -> bool:
    if not _table_exists(table):
        return False
    return index in {i["name"] for i in _inspector().get_indexes(table, schema=SCHEMA)}


def _ensure_index(table: str, name: str, columns: list[str], **kwargs) -> None:
    if _index_exists(table, name):
        return
    op.create_index(name, table, columns, schema=SCHEMA, **kwargs)


def _pk(name: str = "id") -> sa.Column:
    return sa.Column(name, sa.Integer(), autoincrement=True, nullable=False)


def _version() -> sa.Column:
    return sa.Column(
        "version", sa.Integer(), nullable=False, server_default=sa.text("1")
    )


def _created_at(name: str = "created_at") -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


def _updated_at() -> sa.Column:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


def _timestamptz(name: str, *, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS reports"))

    if not _table_exists("campaign_groups"):
        op.create_table(
            "campaign_groups",
            _pk(),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("client", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            _version(),
            _created_at(),
            _updated_at(),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name", name="uix_campaign_groups_name"),
            schema=SCHEMA,
        )

    if not _table_exists("programs"):
        op.create_table(
            "programs",
            _pk(),
            sa.Column("campaign_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("format", sa.Text(), nullable=False),
            sa.Column(
                "status",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'active'"),
            ),
            sa.Column("platform_tool_program_id", sa.Text(), nullable=True),
            _version(),
            _created_at(),
            _updated_at(),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["campaign_id"],
                ["public.campaigns.id"],
                ondelete="CASCADE",
                name="fk_programs_campaign_id",
            ),
            schema=SCHEMA,
        )
    _ensure_index("programs", "programs_campaign_idx", ["campaign_id"])

    if not _table_exists("sessions"):
        op.create_table(
            "sessions",
            _pk(),
            sa.Column("program_id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.Text(), nullable=False),
            sa.Column("zoom_meeting_id", sa.Text(), nullable=True),
            sa.Column("zoom_meeting_uuid", sa.Text(), nullable=True),
            sa.Column("title", sa.Text(), nullable=True),
            _timestamptz("session_date"),
            sa.Column("transcript_s3_key", sa.Text(), nullable=True),
            _version(),
            _created_at(),
            _updated_at(),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["program_id"],
                ["reports.programs.id"],
                ondelete="CASCADE",
                name="fk_sessions_program_id",
            ),
            sa.UniqueConstraint(
                "zoom_meeting_uuid", name="uix_sessions_zoom_meeting_uuid"
            ),
            schema=SCHEMA,
        )
    _ensure_index("sessions", "sessions_program_idx", ["program_id"])
    _ensure_index("sessions", "sessions_date_idx", ["session_date"])

    if not _table_exists("clips"):
        op.create_table(
            "clips",
            _pk(),
            sa.Column("program_id", sa.Integer(), nullable=False),
            sa.Column("session_id", sa.Integer(), nullable=True),
            sa.Column("youtube_video_id", sa.Text(), nullable=True),
            sa.Column("title", sa.Text(), nullable=True),
            sa.Column("duration_seconds", sa.Integer(), nullable=True),
            _timestamptz("published_at"),
            _version(),
            _created_at(),
            _updated_at(),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["program_id"],
                ["reports.programs.id"],
                ondelete="CASCADE",
                name="fk_clips_program_id",
            ),
            sa.ForeignKeyConstraint(
                ["session_id"],
                ["reports.sessions.id"],
                ondelete="SET NULL",
                name="fk_clips_session_id",
            ),
            sa.UniqueConstraint(
                "youtube_video_id", name="uix_clips_youtube_video_id"
            ),
            schema=SCHEMA,
        )
    _ensure_index("clips", "clips_program_idx", ["program_id"])
    _ensure_index("clips", "clips_youtube_idx", ["youtube_video_id"])

    if not _table_exists("survey_responses"):
        op.create_table(
            "survey_responses",
            _pk(),
            sa.Column("session_id", sa.Integer(), nullable=False),
            sa.Column("respondent_id", sa.Text(), nullable=True),
            sa.Column(
                "source",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'native'"),
            ),
            _timestamptz("submitted_at", nullable=False),
            sa.Column("payload", postgresql.JSONB(), nullable=False),
            sa.Column("cohort", sa.Text(), nullable=True),
            _version(),
            _created_at(),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["session_id"],
                ["reports.sessions.id"],
                ondelete="CASCADE",
                name="fk_survey_responses_session_id",
            ),
            schema=SCHEMA,
        )
    _ensure_index(
        "survey_responses", "survey_responses_session_idx", ["session_id"]
    )
    _ensure_index("survey_responses", "survey_responses_cohort_idx", ["cohort"])
    _ensure_index("survey_responses", "survey_responses_source_idx", ["source"])

    if not _table_exists("qa_entries"):
        op.create_table(
            "qa_entries",
            _pk(),
            sa.Column("session_id", sa.Integer(), nullable=False),
            sa.Column("asker_name", sa.Text(), nullable=True),
            sa.Column("question_text", sa.Text(), nullable=False),
            sa.Column(
                "answered",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            _timestamptz("asked_at", nullable=False),
            sa.Column(
                "themes",
                postgresql.ARRAY(sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            sa.Column("tagged_by", sa.Text(), nullable=True),
            _timestamptz("tagged_at"),
            _version(),
            _created_at(),
            _updated_at(),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["session_id"],
                ["reports.sessions.id"],
                ondelete="CASCADE",
                name="fk_qa_entries_session_id",
            ),
            schema=SCHEMA,
        )
    _ensure_index("qa_entries", "qa_entries_session_idx", ["session_id"])
    _ensure_index(
        "qa_entries",
        "qa_entries_themes_gin",
        ["themes"],
        postgresql_using="gin",
    )

    if not _table_exists("attendance"):
        op.create_table(
            "attendance",
            _pk(),
            sa.Column("session_id", sa.Integer(), nullable=False),
            sa.Column("attendee_email", sa.Text(), nullable=True),
            sa.Column("attendee_name", sa.Text(), nullable=True),
            _timestamptz("joined_at"),
            _timestamptz("left_at"),
            sa.Column("duration_seconds", sa.Integer(), nullable=True),
            sa.Column("source", sa.Text(), nullable=True),
            _created_at(),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["session_id"],
                ["reports.sessions.id"],
                ondelete="CASCADE",
                name="fk_attendance_session_id",
            ),
            schema=SCHEMA,
        )
    _ensure_index("attendance", "attendance_session_idx", ["session_id"])

    if not _table_exists("clip_analytics"):
        op.create_table(
            "clip_analytics",
            _pk(),
            sa.Column("clip_id", sa.Integer(), nullable=False),
            sa.Column("channel", sa.Text(), nullable=False),
            sa.Column("metric_date", sa.Date(), nullable=False),
            sa.Column("views", sa.Integer(), nullable=True),
            sa.Column("impressions", sa.Integer(), nullable=True),
            sa.Column("engaged_views", sa.Integer(), nullable=True),
            sa.Column("retention_pct", sa.Numeric(5, 2), nullable=True),
            sa.Column("engagement_rate", sa.Numeric(5, 2), nullable=True),
            sa.Column("raw", postgresql.JSONB(), nullable=True),
            _timestamptz("fetched_at", nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["clip_id"],
                ["reports.clips.id"],
                ondelete="CASCADE",
                name="fk_clip_analytics_clip_id",
            ),
            sa.UniqueConstraint(
                "clip_id",
                "channel",
                "metric_date",
                name="uix_clip_analytics_clip_channel_date",
            ),
            schema=SCHEMA,
        )
    _ensure_index("clip_analytics", "clip_analytics_clip_idx", ["clip_id"])
    _ensure_index("clip_analytics", "clip_analytics_channel_idx", ["channel"])

    if not _table_exists("campaign_analytics"):
        op.create_table(
            "campaign_analytics",
            _pk(),
            sa.Column("campaign_id", sa.Integer(), nullable=False),
            sa.Column("channel", sa.Text(), nullable=False),
            sa.Column("metric_date", sa.Date(), nullable=False),
            sa.Column("reach", sa.Integer(), nullable=True),
            sa.Column("impressions", sa.Integer(), nullable=True),
            sa.Column("engaged", sa.Integer(), nullable=True),
            sa.Column("demographic", postgresql.JSONB(), nullable=True),
            sa.Column("raw", postgresql.JSONB(), nullable=True),
            _timestamptz("fetched_at", nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["campaign_id"],
                ["public.campaigns.id"],
                ondelete="CASCADE",
                name="fk_campaign_analytics_campaign_id",
            ),
            sa.UniqueConstraint(
                "campaign_id",
                "channel",
                "metric_date",
                name="uix_campaign_analytics_campaign_channel_date",
            ),
            schema=SCHEMA,
        )
    _ensure_index(
        "campaign_analytics",
        "campaign_analytics_campaign_idx",
        ["campaign_id"],
    )

    if not _table_exists("market_events"):
        op.create_table(
            "market_events",
            _pk(),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("event_date", sa.Date(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Text(), nullable=True),
            _version(),
            _created_at(),
            _updated_at(),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "name", "event_date", name="uix_market_events_name_date"
            ),
            schema=SCHEMA,
        )

    if not _table_exists("campaign_market_events"):
        op.create_table(
            "campaign_market_events",
            sa.Column("campaign_id", sa.Integer(), nullable=False),
            sa.Column("market_event_id", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint(
                "campaign_id",
                "market_event_id",
                name="pk_campaign_market_events",
            ),
            sa.ForeignKeyConstraint(
                ["campaign_id"],
                ["public.campaigns.id"],
                ondelete="CASCADE",
                name="fk_campaign_market_events_campaign_id",
            ),
            sa.ForeignKeyConstraint(
                ["market_event_id"],
                ["reports.market_events.id"],
                ondelete="CASCADE",
                name="fk_campaign_market_events_market_event_id",
            ),
            schema=SCHEMA,
        )

    if not _table_exists("sponsor_sov"):
        op.create_table(
            "sponsor_sov",
            _pk(),
            sa.Column("session_id", sa.Integer(), nullable=False),
            sa.Column("sponsor_name", sa.Text(), nullable=False),
            sa.Column("share_pct", sa.Numeric(5, 2), nullable=True),
            _created_at(),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["session_id"],
                ["reports.sessions.id"],
                ondelete="CASCADE",
                name="fk_sponsor_sov_session_id",
            ),
            sa.UniqueConstraint(
                "session_id",
                "sponsor_name",
                name="uix_sponsor_sov_session_sponsor",
            ),
            schema=SCHEMA,
        )

    if not _table_exists("report_templates"):
        op.create_table(
            "report_templates",
            _pk(),
            sa.Column("template_type", sa.Text(), nullable=False),
            sa.Column("version", sa.Text(), nullable=False),
            sa.Column("docx_template_key", sa.Text(), nullable=False),
            sa.Column("prompt_text", sa.Text(), nullable=False),
            sa.Column(
                "active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column("created_by", sa.Text(), nullable=True),
            _created_at(),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "template_type",
                "version",
                name="uix_report_templates_type_version",
            ),
            schema=SCHEMA,
        )
    _ensure_index(
        "report_templates",
        "report_templates_type_active_idx",
        ["template_type", "active"],
    )

    if not _table_exists("reports"):
        op.create_table(
            "reports",
            _pk(),
            sa.Column("campaign_id", sa.Integer(), nullable=True),
            sa.Column("campaign_group_id", sa.Integer(), nullable=True),
            sa.Column("template_id", sa.Integer(), nullable=False),
            sa.Column("template_version", sa.Text(), nullable=False),
            sa.Column("prompt_version", sa.Text(), nullable=False),
            sa.Column("generated_by", sa.Text(), nullable=True),
            sa.Column(
                "status",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'queued'"),
            ),
            sa.Column("finish_reason", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("s3_key", sa.Text(), nullable=True),
            sa.Column("input_completeness", postgresql.JSONB(), nullable=True),
            sa.Column("group_snapshot", postgresql.JSONB(), nullable=True),
            sa.Column("latency_ms", postgresql.JSONB(), nullable=True),
            sa.Column("tokens_input", sa.Integer(), nullable=True),
            sa.Column("tokens_output", sa.Integer(), nullable=True),
            sa.Column("request_id", sa.Text(), nullable=True),
            _created_at("queued_at"),
            _timestamptz("started_at"),
            _timestamptz("completed_at"),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["campaign_id"],
                ["public.campaigns.id"],
                name="fk_reports_campaign_id",
            ),
            sa.ForeignKeyConstraint(
                ["campaign_group_id"],
                ["reports.campaign_groups.id"],
                name="fk_reports_campaign_group_id",
            ),
            sa.ForeignKeyConstraint(
                ["template_id"],
                ["reports.report_templates.id"],
                name="fk_reports_template_id",
            ),
            sa.CheckConstraint(
                "campaign_id IS NOT NULL OR campaign_group_id IS NOT NULL",
                name="ck_reports_campaign_or_group",
            ),
            schema=SCHEMA,
        )
    _ensure_index("reports", "reports_campaign_idx", ["campaign_id"])
    _ensure_index("reports", "reports_group_idx", ["campaign_group_id"])
    _ensure_index("reports", "reports_status_idx", ["status"])
    _ensure_index("reports", "reports_generated_by_idx", ["generated_by"])

    if not _table_exists("ingest_jobs"):
        op.create_table(
            "ingest_jobs",
            _pk(),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("campaign_id", sa.Integer(), nullable=True),
            sa.Column("kind", sa.Text(), nullable=False),
            sa.Column(
                "status",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'queued'"),
            ),
            sa.Column("triggered_by", sa.Text(), nullable=True),
            sa.Column("rows_written", sa.Integer(), nullable=True),
            sa.Column("rows_skipped", sa.Integer(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            _created_at("queued_at"),
            _timestamptz("started_at"),
            _timestamptz("completed_at"),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["campaign_id"],
                ["public.campaigns.id"],
                name="fk_ingest_jobs_campaign_id",
            ),
            schema=SCHEMA,
        )
    _ensure_index("ingest_jobs", "ingest_jobs_source_idx", ["source"])
    _ensure_index("ingest_jobs", "ingest_jobs_campaign_idx", ["campaign_id"])
    _ensure_index("ingest_jobs", "ingest_jobs_status_idx", ["status"])


def downgrade() -> None:
    for name in _TABLES_DROP_ORDER:
        if _table_exists(name):
            op.drop_table(name, schema=SCHEMA)
    op.execute(sa.text("DROP SCHEMA IF EXISTS reports"))
