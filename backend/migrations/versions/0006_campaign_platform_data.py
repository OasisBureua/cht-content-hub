"""Consolidate csv_uploads + platform_snapshots into campaign_platform_data."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_campaign_platform_data"
down_revision: Union[str, None] = "0005_platform_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "campaign_platform_data",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("fetch_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="missing"),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("rows", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="api"),
        sa.Column("filename", sa.String(length=500), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "campaign_id",
            "platform",
            "fetch_date",
            name="uix_campaign_platform_fetch_date",
        ),
    )
    op.create_index(
        "ix_campaign_platform_data_campaign_id",
        "campaign_platform_data",
        ["campaign_id"],
    )

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "campaign_csv_uploads" in tables:
        op.execute(
            sa.text(
                """
                INSERT INTO campaign_platform_data (
                    campaign_id, platform, fetch_date, status, synced_at,
                    row_count, rows, source, filename, updated_at
                )
                SELECT
                    campaign_id,
                    platform,
                    (uploaded_at AT TIME ZONE 'UTC')::date,
                    'available',
                    uploaded_at,
                    row_count,
                    rows,
                    'csv',
                    filename,
                    uploaded_at
                FROM campaign_csv_uploads
                ON CONFLICT (campaign_id, platform, fetch_date) DO UPDATE SET
                    status = EXCLUDED.status,
                    synced_at = EXCLUDED.synced_at,
                    row_count = EXCLUDED.row_count,
                    rows = EXCLUDED.rows,
                    source = EXCLUDED.source,
                    filename = EXCLUDED.filename,
                    updated_at = EXCLUDED.updated_at
                """
            )
        )
        op.drop_index("ix_campaign_csv_uploads_campaign_id", table_name="campaign_csv_uploads")
        op.drop_table("campaign_csv_uploads")

    if "campaign_platform_snapshots" in tables:
        op.execute(
            sa.text(
                """
                INSERT INTO campaign_platform_data (
                    campaign_id, platform, fetch_date, status, synced_at,
                    next_sync_at, row_count, rows, raw, source, error, updated_at
                )
                SELECT
                    campaign_id,
                    platform,
                    COALESCE((synced_at AT TIME ZONE 'UTC')::date, CURRENT_DATE),
                    status,
                    synced_at,
                    next_sync_at,
                    row_count,
                    rows,
                    raw,
                    'api',
                    error,
                    updated_at
                FROM campaign_platform_snapshots
                ON CONFLICT (campaign_id, platform, fetch_date) DO UPDATE SET
                    status = EXCLUDED.status,
                    synced_at = EXCLUDED.synced_at,
                    next_sync_at = EXCLUDED.next_sync_at,
                    row_count = EXCLUDED.row_count,
                    rows = EXCLUDED.rows,
                    raw = EXCLUDED.raw,
                    source = EXCLUDED.source,
                    error = EXCLUDED.error,
                    updated_at = EXCLUDED.updated_at
                """
            )
        )
        op.drop_index(
            "ix_campaign_platform_snapshots_campaign_id",
            table_name="campaign_platform_snapshots",
        )
        op.drop_table("campaign_platform_snapshots")


def downgrade() -> None:
    op.create_table(
        "campaign_csv_uploads",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("rows", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "platform", name="uix_campaign_csv_platform"),
    )
    op.create_index("ix_campaign_csv_uploads_campaign_id", "campaign_csv_uploads", ["campaign_id"])

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
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "platform", name="uix_campaign_platform_snapshot"),
    )
    op.create_index(
        "ix_campaign_platform_snapshots_campaign_id",
        "campaign_platform_snapshots",
        ["campaign_id"],
    )

    op.drop_index("ix_campaign_platform_data_campaign_id", table_name="campaign_platform_data")
    op.drop_table("campaign_platform_data")
