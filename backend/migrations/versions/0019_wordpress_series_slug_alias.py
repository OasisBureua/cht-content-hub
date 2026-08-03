"""Add series_slug_alias table (WPR-8 / SCRUM-159).

Tracks series slug renames so external links (CHT playlist detail pages,
old bookmarks, third-party embeds) keep resolving after Andrew renames a
series in wp-admin.

When mu-plugin v0.6 fires a term_updated event for a `term_id` that
ContentHub already tracks under a different slug, projection logic inserts
a row here (`old_slug` → `current_slug`), atomically updates the master
row's slug on wordpress_series, and moves the M:M memberships to the new
slug so downstream queries stay correct.

CHT's playlist detail route catches `/playlist/series/{old-slug}`, looks
up the alias table, and issues a 301 to `/playlist/series/{current-slug}`.

Design:
- `old_slug` is the primary key — one row per historical slug that was
  ever used for this series.
- `current_slug` FKs to `wordpress_series.slug` with ON UPDATE CASCADE
  behavior applied at the projection layer (we UPDATE the parent row
  slug, not DELETE + INSERT, so FK constraints remain valid).
- `renamed_at` records when we observed the rename — for audit + potential
  cleanup of very old aliases if needed.

Note on scope: this table covers `series` only for now. Categories and
tags rarely rename in practice; adding parallel alias tables is trivial
future work if either taxonomy needs the same treatment.

Revision ID: 0019_wordpress_series_slug_alias
Revises: 0018_wordpress_posts_coalesced
Create Date: 2026-07-29
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

revision: str = "0019_wordpress_series_slug_alias"
down_revision: Union[str, None] = "0018_wordpress_posts_coalesced"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("wordpress_series_slug_alias"):
        op.create_table(
            "wordpress_series_slug_alias",
            sa.Column("old_slug", sa.String(length=200), primary_key=True),
            sa.Column(
                "current_slug", sa.String(length=200), nullable=False
            ),
            sa.Column(
                "renamed_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["current_slug"],
                ["wordpress_series.slug"],
                name="fk_wp_series_alias_current",
                ondelete="CASCADE",
            ),
        )
    if not index_exists(
        "wordpress_series_slug_alias", "ix_wp_series_alias_current"
    ):
        op.create_index(
            "ix_wp_series_alias_current",
            "wordpress_series_slug_alias",
            ["current_slug"],
            unique=False,
        )


def downgrade() -> None:
    if table_exists("wordpress_series_slug_alias"):
        op.drop_table("wordpress_series_slug_alias")
