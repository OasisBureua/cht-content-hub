"""Add series JSONB column to wordpress_events.

WPR-2 Sub-unit A of the CHT ↔ WordPress reorganization
(SCRUM-153 / SCRUM-151 parent).

The `series` taxonomy is a custom WordPress taxonomy Andrew uses to group
doctor-pair episodes into logical playlists. WordPress currently has 101
series terms. Round 1 of the WP↔CHT connection mirrored categories + tags
but skipped series entirely — this migration adds first-class storage for
per-post series assignments alongside the existing `categories` + `tags`
JSONB arrays.

Storage shape mirrors categories/tags exactly: JSONB array of slug strings,
open-vocabulary (new series terms flow through without schema change),
NOT NULL with `[]` default so existing rows are safe.

The many-to-many `wordpress_series` + `wordpress_post_series` term-level
tables that Phase 1 also introduces are separate migrations — this one is
scoped strictly to the payload-level per-post projection so mu-plugin v0.5
has a home for its new `series` payload field.

Revision ID: 0014_wordpress_events_series
Revises: 0013_tagger_observability
Create Date: 2026-07-28
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


revision: str = "0014_wordpress_events_series"
down_revision: Union[str, None] = "0013_tagger_observability"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column_name in {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    if not _column_exists("wordpress_events", "series"):
        op.add_column(
            "wordpress_events",
            sa.Column(
                "series",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default="[]",
            ),
        )


def downgrade() -> None:
    if _column_exists("wordpress_events", "series"):
        op.drop_column("wordpress_events", "series")
