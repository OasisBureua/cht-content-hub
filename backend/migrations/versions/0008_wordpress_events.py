"""Create wordpress_events table — raw event log for WordPress ingest.

Powers the WordPress → contenthub webhook ingest pipeline. Every publish /
update / delete event from Andrew's WordPress site lands here as a row.
Downstream parsing (Content ID → disease-state categorization, playlist
fan-out, cache invalidation) reads from this table.

Idempotency: UNIQUE (post_id, modified_gmt) — the mu-plugin dedup key
mirrored on the DB side.

Revision ID: 0008_wordpress_events
Revises: 0007_playlist_tags
Create Date: 2026-07-09
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


revision: str = "0008_wordpress_events"
down_revision: Union[str, None] = "0007_playlist_tags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wordpress_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("modified_gmt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event", sa.String(length=16), nullable=False),
        sa.Column("post_type", sa.String(length=64), nullable=False),
        sa.Column("slug", sa.String(length=500), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("permalink", sa.String(length=1000), nullable=False),
        sa.Column(
            "categories",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("site_url", sa.String(length=500), nullable=False),
        sa.Column("acf", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "raw_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "signature_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "post_id", "modified_gmt", name="uix_wordpress_events_post_modified"
        ),
    )
    op.create_index("ix_wordpress_events_post_id", "wordpress_events", ["post_id"])
    op.create_index("ix_wordpress_events_event", "wordpress_events", ["event"])
    op.create_index(
        "ix_wordpress_events_received_at", "wordpress_events", ["received_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_wordpress_events_received_at", table_name="wordpress_events")
    op.drop_index("ix_wordpress_events_event", table_name="wordpress_events")
    op.drop_index("ix_wordpress_events_post_id", table_name="wordpress_events")
    op.drop_table("wordpress_events")
