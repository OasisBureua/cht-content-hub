"""Platform snapshots, sync audit log, integration settings (non-HubSpot)."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import index_exists, table_exists

revision: str = "0005_platform_snapshots"
down_revision: Union[str, None] = "0004_drop_integration_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("campaign_platform_snapshots"):
        op.create_table(
            "campaign_platform_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="missing"),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("rows", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "platform", name="uix_campaign_platform_snapshot"),
        )
    if not index_exists("campaign_platform_snapshots", "ix_campaign_platform_snapshots_campaign_id"):
        op.create_index(
            "ix_campaign_platform_snapshots_campaign_id",
            "campaign_platform_snapshots",
            ["campaign_id"],
        )

    if not table_exists("platform_sync_runs"):
        op.create_table(
            "platform_sync_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        )
    if not index_exists("platform_sync_runs", "ix_platform_sync_runs_campaign_id"):
        op.create_index(
            "ix_platform_sync_runs_campaign_id",
            "platform_sync_runs",
            ["campaign_id"],
        )

    if not table_exists("integration_settings"):
        op.create_table(
            "integration_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("integration_settings")
    op.drop_index("ix_platform_sync_runs_campaign_id", table_name="platform_sync_runs")
    op.drop_table("platform_sync_runs")
    op.drop_index(
        "ix_campaign_platform_snapshots_campaign_id",
        table_name="campaign_platform_snapshots",
    )
    op.drop_table("campaign_platform_snapshots")
