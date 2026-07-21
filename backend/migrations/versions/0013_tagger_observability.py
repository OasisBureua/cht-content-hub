"""Tagger observability tables (SCRUM-78).

Persists every playlist_doctor_tagger run for admin UI + alarm inputs:

- `tagger_runs`   : one row per run — stats snapshot + started_at/finished_at
- `tag_diffs`     : one row per (Shoot|Clip|Post) tag mutation observed
                    during a run — curator-facing audit trail

CloudWatch alarms use `tagger_runs.clips_changed + posts_changed` over the
last 24h window to page on 'nothing propagated' regressions.

Revision ID: 0013_tagger_observability
Revises: 0012_clip_curator_tag_override
Create Date: 2026-07-20
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from path_setup import install  # noqa: E402

install()

from migrations.helpers import index_exists  # noqa: E402

revision: str = "0013_tagger_observability"
down_revision: Union[str, None] = "0012_clip_curator_tag_override"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tagger_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("shoots_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shoots_doctors_corrected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clips_changed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("posts_changed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clips_curator_locked_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("posts_curator_locked_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("orphaned_404_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("api_error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clip_post_skipped_models_missing", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    if not index_exists("tagger_runs", "ix_tagger_runs_finished_at"):
        op.create_index(
            "ix_tagger_runs_finished_at",
            "tagger_runs",
            ["finished_at"],
        )

    op.create_table(
        "tag_diffs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("tagger_runs.id"), nullable=False),
        sa.Column("entity_type", sa.String(16), nullable=False),
        sa.Column("entity_id", sa.String(255), nullable=False),
        sa.Column("shoot_id", sa.String(255), nullable=False),
        sa.Column("shoot_name", sa.String(500), nullable=False, server_default=""),
        sa.Column("provider_post_id", sa.String(255), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column(
            "before_tags",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"),
            nullable=False,
            server_default=sa.text("'[]'::jsonb")
            if op.get_bind().dialect.name == "postgresql"
            else sa.text("'[]'"),
        ),
        sa.Column(
            "after_tags",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"),
            nullable=False,
            server_default=sa.text("'[]'::jsonb")
            if op.get_bind().dialect.name == "postgresql"
            else sa.text("'[]'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    if not index_exists("tag_diffs", "ix_tag_diffs_created_at"):
        op.create_index("ix_tag_diffs_created_at", "tag_diffs", ["created_at"])
    if not index_exists("tag_diffs", "ix_tag_diffs_run_id"):
        op.create_index("ix_tag_diffs_run_id", "tag_diffs", ["run_id"])


def downgrade() -> None:
    op.drop_table("tag_diffs")
    op.drop_table("tagger_runs")
