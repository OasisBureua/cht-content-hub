"""Add wordpress_series + wordpress_post_series projected-state tables.

WPR-2 Sub-unit B of CHT ↔ WordPress reorganization (SCRUM-153).

Introduces Layer 2 of the WordPress mirror for the `series` custom
taxonomy — the projected current-state layer that CHT read paths
query directly, distinct from the append-only event log
(`wordpress_events`, Layer 1).

`wordpress_series` — one row per unique series term. Slug is the natural
primary key mirroring WordPress's canonical identifier. Metadata fields
(name, description, parent_slug, wp_term_id) populate from:
  1. mu-plugin v0.6 term-lifecycle webhooks (real-time on Andrew's edits)
  2. Backfill Lambda on first-run seed + drift catch-up
  3. Slug-only UPSERT during post-event ingest for terms we haven't seen yet
     (defensive — display name defaults to slug until reconcile fills it in)

`wordpress_post_series` — many-to-many association between wordpress_posts
and wordpress_series. Composite primary key (post_id, series_slug) enforces
uniqueness. FK cascade on delete of either side keeps the join table
consistent.

Revision ID: 0015_wordpress_series_terms
Revises: 0014_wordpress_events_series
Create Date: 2026-07-28
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

from migrations.helpers import index_exists, table_exists  # noqa: E402

revision: str = "0015_wordpress_series_terms"
down_revision: Union[str, None] = "0014_wordpress_events_series"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("wordpress_series"):
        op.create_table(
            "wordpress_series",
            sa.Column("slug", sa.String(length=200), primary_key=True),
            sa.Column("name", sa.String(length=500), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("parent_slug", sa.String(length=200), nullable=True),
            sa.Column("wp_term_id", sa.Integer(), nullable=True),
            sa.Column(
                "first_seen",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "last_updated",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )
    if not index_exists("wordpress_series", "ix_wordpress_series_wp_term_id"):
        op.create_index(
            "ix_wordpress_series_wp_term_id",
            "wordpress_series",
            ["wp_term_id"],
            unique=False,
        )

    if not table_exists("wordpress_post_series"):
        op.create_table(
            "wordpress_post_series",
            sa.Column("post_id", sa.Integer(), nullable=False),
            sa.Column("series_slug", sa.String(length=200), nullable=False),
            sa.Column(
                "assigned_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("post_id", "series_slug"),
            sa.ForeignKeyConstraint(
                ["series_slug"],
                ["wordpress_series.slug"],
                name="fk_wp_post_series_slug",
                ondelete="CASCADE",
            ),
        )
    if not index_exists("wordpress_post_series", "ix_wp_post_series_series_slug"):
        op.create_index(
            "ix_wp_post_series_series_slug",
            "wordpress_post_series",
            ["series_slug"],
            unique=False,
        )


def downgrade() -> None:
    if table_exists("wordpress_post_series"):
        op.drop_table("wordpress_post_series")
    if table_exists("wordpress_series"):
        op.drop_table("wordpress_series")
