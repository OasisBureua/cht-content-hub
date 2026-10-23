"""CPR-15: posts → campaign links + daily metrics; drop the empty reports schema.

* ``posts``: ``provider_account_id`` (YouTube channel / LinkedIn account),
  ``alt_ids`` (other IDs for the same post, e.g. LinkedIn share/activity
  URNs), ``promotes_post_id`` (an ad points to the organic post it boosts),
  ``excluded``.
* ``post_campaign_links``: which campaign (and Platform program / CHM
  Content ID) a post belongs to, how the link was made, and its status.
* ``post_metrics_daily``: one metrics row per post, day and source.
* ``platform_sync_runs.campaign_id`` is nullable: source syncs are not per
  campaign.
* ``reports.*`` (0025) never received a row and nothing reads it.

Revision ID: 0032_social_posts
Revises: 0031_export_survey_questions
"""

from __future__ import annotations

import importlib.util
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

from migrations.helpers import column_exists, index_exists, table_exists  # noqa: E402

revision: str = "0032_social_posts"
down_revision: Union[str, None] = "0031_export_survey_questions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _reports_migration():
    path = Path(__file__).resolve().parent / "0025_reports_schema.py"
    spec = importlib.util.spec_from_file_location("_m0025_reports_schema", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade() -> None:
    if not column_exists("posts", "provider_account_id"):
        op.add_column("posts", sa.Column("provider_account_id", sa.String(64), nullable=True))
    if not column_exists("posts", "alt_ids"):
        op.add_column("posts", sa.Column("alt_ids", postgresql.ARRAY(sa.String()), nullable=True))
    if not column_exists("posts", "promotes_post_id"):
        op.add_column(
            "posts",
            sa.Column(
                "promotes_post_id",
                sa.String(255),
                sa.ForeignKey("posts.id", ondelete="SET NULL", name="fk_posts_promotes_post"),
                nullable=True,
            ),
        )
    if not column_exists("posts", "excluded"):
        op.add_column(
            "posts",
            sa.Column("excluded", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if not index_exists("posts", "ix_posts_provider_account_id"):
        op.create_index("ix_posts_provider_account_id", "posts", ["provider_account_id"])

    if not table_exists("post_campaign_links"):
        op.create_table(
            "post_campaign_links",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "post_id",
                sa.String(255),
                sa.ForeignKey("posts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "campaign_id",
                sa.Integer(),
                sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("platform_program_id", sa.String(64), nullable=True),
            sa.Column("chm_content_id", sa.String(64), nullable=True),
            sa.Column("method", sa.String(32), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="active"),
            sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("removed_by", sa.String(255), nullable=True),
            sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint("post_id", "campaign_id", name="uix_post_campaign_links_post_campaign"),
        )
        op.create_index("ix_post_campaign_links_campaign_id", "post_campaign_links", ["campaign_id"])

    if not table_exists("post_metrics_daily"):
        op.create_table(
            "post_metrics_daily",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "post_id",
                sa.String(255),
                sa.ForeignKey("posts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("metric_date", sa.Date(), nullable=False),
            sa.Column("source", sa.String(32), nullable=False),
            sa.Column("basis", sa.String(20), nullable=False),
            sa.Column("metrics", postgresql.JSONB(), nullable=False),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "post_id", "metric_date", "source", name="uix_post_metrics_daily_post_date_source"
            ),
        )
        op.create_index("ix_post_metrics_daily_metric_date", "post_metrics_daily", ["metric_date"])

    op.alter_column("platform_sync_runs", "campaign_id", existing_type=sa.Integer(), nullable=True)

    reports = _reports_migration()
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names(schema=reports.SCHEMA)) if _has_reports_schema() else set()
    for name in reports._TABLES_DROP_ORDER:
        if name in existing:
            op.drop_table(name, schema=reports.SCHEMA)
    op.execute(sa.text(f"DROP SCHEMA IF EXISTS {reports.SCHEMA}"))


def _has_reports_schema() -> bool:
    return "reports" in sa.inspect(op.get_bind()).get_schema_names()


def downgrade() -> None:
    _reports_migration().upgrade()

    op.execute(sa.text("DELETE FROM platform_sync_runs WHERE campaign_id IS NULL"))
    op.alter_column("platform_sync_runs", "campaign_id", existing_type=sa.Integer(), nullable=False)

    for table in ("post_metrics_daily", "post_campaign_links"):
        if table_exists(table):
            op.drop_table(table)
    if index_exists("posts", "ix_posts_provider_account_id"):
        op.drop_index("ix_posts_provider_account_id", table_name="posts")
    for column in ("excluded", "promotes_post_id", "alt_ids", "provider_account_id"):
        if column_exists("posts", column):
            op.drop_column("posts", column)
