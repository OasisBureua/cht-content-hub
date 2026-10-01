"""CPR-13: Zoom export warehouse tables (sessions, attendance, surveys, runs).

Creates flat ``export_*`` tables in the public schema (assumption A1 from
the CPR-13 plan — not a separate Postgres ``reports`` schema yet).

Chain note: this revision and ``0022_shoot_campaign_link`` both revise
``0021_wp_tag_namespace_map``. They are joined by ``0023_merge_cpr13_heads``.

Revision ID: 0022_export_zoom_warehouse
Revises: 0021_wp_tag_namespace_map
Create Date: 2026-09-22
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from path_setup import install  # noqa: E402

install()

from migrations.helpers import index_exists, table_exists  # noqa: E402

revision: str = "0022_export_zoom_warehouse"
down_revision: Union[str, None] = "0021_wp_tag_namespace_map"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("export_sessions"):
        op.create_table(
            "export_sessions",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("platform_tool_program_id", sa.String(length=64), nullable=False),
            sa.Column("campaign_id", sa.Integer(), nullable=True),
            sa.Column("kind", sa.String(length=32), nullable=True),
            sa.Column("title", sa.String(length=500), nullable=True),
            sa.Column("session_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("zoom_meeting_id", sa.String(length=128), nullable=True),
            sa.Column("zoom_uuid", sa.String(length=128), nullable=True),
            sa.Column("transcript_s3_key", sa.String(length=1000), nullable=True),
            sa.Column("transcript_text", sa.Text(), nullable=True),
            sa.Column("zoom_session_ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["campaign_id"], ["campaigns.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "platform_tool_program_id",
                name="uix_export_sessions_platform_tool_program_id",
            ),
        )
    if not index_exists("export_sessions", "ix_export_sessions_platform_tool_program_id"):
        op.create_index(
            "ix_export_sessions_platform_tool_program_id",
            "export_sessions",
            ["platform_tool_program_id"],
        )
    if not index_exists("export_sessions", "ix_export_sessions_campaign_id"):
        op.create_index(
            "ix_export_sessions_campaign_id",
            "export_sessions",
            ["campaign_id"],
        )

    if not table_exists("export_attendance_events"):
        op.create_table(
            "export_attendance_events",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("dedupe_key", sa.String(length=512), nullable=False),
            sa.Column("platform_tool_program_id", sa.String(length=64), nullable=False),
            sa.Column("campaign_id", sa.Integer(), nullable=True),
            sa.Column("source", sa.String(length=32), nullable=False),
            sa.Column("event", sa.String(length=16), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("participant_email", sa.String(length=320), nullable=True),
            sa.Column("participant_name", sa.String(length=255), nullable=True),
            sa.Column("duration_seconds", sa.Integer(), nullable=True),
            sa.Column("platform_event_id", sa.String(length=128), nullable=True),
            sa.Column("zoom_participant_id", sa.String(length=128), nullable=True),
            sa.Column("zoom_meeting_id", sa.String(length=128), nullable=True),
            sa.Column("join_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("leave_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["campaign_id"], ["campaigns.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["platform_tool_program_id"],
                ["export_sessions.platform_tool_program_id"],
                name="fk_export_attendance_program",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "dedupe_key", name="uix_export_attendance_dedupe_key"
            ),
        )
    if not index_exists(
        "export_attendance_events", "ix_export_attendance_events_program_id"
    ):
        op.create_index(
            "ix_export_attendance_events_program_id",
            "export_attendance_events",
            ["platform_tool_program_id"],
        )
    if not index_exists(
        "export_attendance_events", "ix_export_attendance_events_campaign_id"
    ):
        op.create_index(
            "ix_export_attendance_events_campaign_id",
            "export_attendance_events",
            ["campaign_id"],
        )
    if not index_exists(
        "export_attendance_events", "ix_export_attendance_events_occurred_at"
    ):
        op.create_index(
            "ix_export_attendance_events_occurred_at",
            "export_attendance_events",
            ["occurred_at"],
        )

    if not table_exists("export_survey_responses"):
        op.create_table(
            "export_survey_responses",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("dedupe_key", sa.String(length=512), nullable=False),
            sa.Column("campaign_id", sa.Integer(), nullable=True),
            sa.Column("platform_tool_program_id", sa.String(length=64), nullable=True),
            sa.Column("respondent_id", sa.String(length=128), nullable=True),
            sa.Column(
                "source",
                sa.String(length=64),
                nullable=False,
                server_default="unknown",
            ),
            sa.Column("survey_type", sa.String(length=64), nullable=True),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("submission_id", sa.String(length=128), nullable=True),
            sa.Column(
                "answers",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["campaign_id"], ["campaigns.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "dedupe_key", name="uix_export_survey_responses_dedupe_key"
            ),
        )
    if not index_exists(
        "export_survey_responses", "ix_export_survey_responses_campaign_id"
    ):
        op.create_index(
            "ix_export_survey_responses_campaign_id",
            "export_survey_responses",
            ["campaign_id"],
        )
    if not index_exists(
        "export_survey_responses", "ix_export_survey_responses_program_id"
    ):
        op.create_index(
            "ix_export_survey_responses_program_id",
            "export_survey_responses",
            ["platform_tool_program_id"],
        )

    if not table_exists("export_ingest_runs"):
        op.create_table(
            "export_ingest_runs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("campaign_id", sa.Integer(), nullable=True),
            sa.Column(
                "trigger",
                sa.String(length=32),
                nullable=False,
                server_default="manual",
            ),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column(
                "sessions_upserted",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "attendance_upserted",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "surveys_upserted",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["campaign_id"], ["campaigns.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    if not index_exists("export_ingest_runs", "ix_export_ingest_runs_campaign_id"):
        op.create_index(
            "ix_export_ingest_runs_campaign_id",
            "export_ingest_runs",
            ["campaign_id"],
        )


def downgrade() -> None:
    if table_exists("export_ingest_runs"):
        if index_exists("export_ingest_runs", "ix_export_ingest_runs_campaign_id"):
            op.drop_index(
                "ix_export_ingest_runs_campaign_id",
                table_name="export_ingest_runs",
            )
        op.drop_table("export_ingest_runs")

    if table_exists("export_survey_responses"):
        if index_exists(
            "export_survey_responses", "ix_export_survey_responses_program_id"
        ):
            op.drop_index(
                "ix_export_survey_responses_program_id",
                table_name="export_survey_responses",
            )
        if index_exists(
            "export_survey_responses", "ix_export_survey_responses_campaign_id"
        ):
            op.drop_index(
                "ix_export_survey_responses_campaign_id",
                table_name="export_survey_responses",
            )
        op.drop_table("export_survey_responses")

    if table_exists("export_attendance_events"):
        if index_exists(
            "export_attendance_events", "ix_export_attendance_events_occurred_at"
        ):
            op.drop_index(
                "ix_export_attendance_events_occurred_at",
                table_name="export_attendance_events",
            )
        if index_exists(
            "export_attendance_events", "ix_export_attendance_events_campaign_id"
        ):
            op.drop_index(
                "ix_export_attendance_events_campaign_id",
                table_name="export_attendance_events",
            )
        if index_exists(
            "export_attendance_events", "ix_export_attendance_events_program_id"
        ):
            op.drop_index(
                "ix_export_attendance_events_program_id",
                table_name="export_attendance_events",
            )
        op.drop_table("export_attendance_events")

    if table_exists("export_sessions"):
        if index_exists("export_sessions", "ix_export_sessions_campaign_id"):
            op.drop_index(
                "ix_export_sessions_campaign_id", table_name="export_sessions"
            )
        if index_exists(
            "export_sessions", "ix_export_sessions_platform_tool_program_id"
        ):
            op.drop_index(
                "ix_export_sessions_platform_tool_program_id",
                table_name="export_sessions",
            )
        op.drop_table("export_sessions")
