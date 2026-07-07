"""Campaign & report admin tables."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_campaigns_admin"
down_revision: Union[str, None] = "0002_kol_slug_and_signal_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "report_templates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
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
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("program_name", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("client_sponsor", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("disease_state", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("treatment_topic", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("reporting_period_start", sa.Date(), nullable=True),
        sa.Column("reporting_period_end", sa.Date(), nullable=True),
        sa.Column(
            "platforms",
            postgresql.ARRAY(sa.String(length=32)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("target_audience", sa.Text(), nullable=False, server_default=""),
        sa.Column("target_regions", sa.Text(), nullable=False, server_default=""),
        sa.Column("target_institutions", sa.Text(), nullable=False, server_default=""),
        sa.Column("physician_speakers", sa.Text(), nullable=False, server_default=""),
        sa.Column("landing_page_url", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("hubspot_campaign_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("livestream_url", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("hubspot_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hubspot_raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "executive_report_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "report_type",
            sa.String(length=32),
            nullable=False,
            server_default="analytics",
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("created_by", sa.String(length=255), nullable=False, server_default=""),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.String(length=128)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("template_id", sa.Integer(), nullable=True),
        sa.Column("ai_insights", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["template_id"], ["report_templates.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "campaign_csv_uploads",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("rows", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "platform", name="uix_campaign_csv_platform"),
    )
    op.create_index(
        "ix_campaign_csv_uploads_campaign_id",
        "campaign_csv_uploads",
        ["campaign_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_campaign_csv_uploads_campaign_id", table_name="campaign_csv_uploads")
    op.drop_table("campaign_csv_uploads")
    op.drop_table("campaigns")
    op.drop_table("report_templates")
