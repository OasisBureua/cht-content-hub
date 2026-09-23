"""Add wordpress_categories + wordpress_post_categories projected-state tables.

WPR-2 Sub-unit B (categories). Same shape as wordpress_series terms +
association — this is Layer 2 projection for the `category` taxonomy.

Rationale for identical shape across all three taxonomies (series,
category, tag): WordPress models them as instances of the same `WP_Term`
type; ContentHub should mirror that uniformity. A future refactor could
collapse to one `wordpress_terms` table with a `taxonomy` discriminator
column, but keeping them separate (a) preserves referential clarity in
downstream code (`WordPressCategory.slug` reads better than
`WordPressTerm.slug where taxonomy='category'`), (b) allows per-taxonomy
indexes without partial-index complexity, (c) doesn't foreclose the merge
later if the redundancy proves painful.

Revision ID: 0016_wordpress_categories_terms
Revises: 0015_wordpress_series_terms
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

revision: str = "0016_wordpress_categories_terms"
down_revision: Union[str, None] = "0015_wordpress_series_terms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("wordpress_categories"):
        op.create_table(
            "wordpress_categories",
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
    if not index_exists(
        "wordpress_categories", "ix_wordpress_categories_wp_term_id"
    ):
        op.create_index(
            "ix_wordpress_categories_wp_term_id",
            "wordpress_categories",
            ["wp_term_id"],
            unique=False,
        )

    if not table_exists("wordpress_post_categories"):
        op.create_table(
            "wordpress_post_categories",
            sa.Column("post_id", sa.Integer(), nullable=False),
            sa.Column("category_slug", sa.String(length=200), nullable=False),
            sa.Column(
                "assigned_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("post_id", "category_slug"),
            sa.ForeignKeyConstraint(
                ["category_slug"],
                ["wordpress_categories.slug"],
                name="fk_wp_post_categories_slug",
                ondelete="CASCADE",
            ),
        )
    if not index_exists(
        "wordpress_post_categories", "ix_wp_post_categories_slug"
    ):
        op.create_index(
            "ix_wp_post_categories_slug",
            "wordpress_post_categories",
            ["category_slug"],
            unique=False,
        )


def downgrade() -> None:
    if table_exists("wordpress_post_categories"):
        op.drop_table("wordpress_post_categories")
    if table_exists("wordpress_categories"):
        op.drop_table("wordpress_categories")
