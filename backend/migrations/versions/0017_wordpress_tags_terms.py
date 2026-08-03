"""Add wordpress_tags + wordpress_post_tags projected-state tables.

WPR-2 Sub-unit B (tags). Same shape as series + categories.

Note: `wp_tag_namespace_map` (WPR-11 / SCRUM-162) is a separate curator-
overlay table that FKs to `wordpress_tags.slug`. This migration establishes
the WP-taxonomy-native structure; namespace projection comes later.

Revision ID: 0017_wordpress_tags_terms
Revises: 0016_wordpress_categories_terms
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

revision: str = "0017_wordpress_tags_terms"
down_revision: Union[str, None] = "0016_wordpress_categories_terms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("wordpress_tags"):
        op.create_table(
            "wordpress_tags",
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
    if not index_exists("wordpress_tags", "ix_wordpress_tags_wp_term_id"):
        op.create_index(
            "ix_wordpress_tags_wp_term_id",
            "wordpress_tags",
            ["wp_term_id"],
            unique=False,
        )

    if not table_exists("wordpress_post_tags"):
        op.create_table(
            "wordpress_post_tags",
            sa.Column("post_id", sa.Integer(), nullable=False),
            sa.Column("tag_slug", sa.String(length=200), nullable=False),
            sa.Column(
                "assigned_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("post_id", "tag_slug"),
            sa.ForeignKeyConstraint(
                ["tag_slug"],
                ["wordpress_tags.slug"],
                name="fk_wp_post_tags_slug",
                ondelete="CASCADE",
            ),
        )
    if not index_exists("wordpress_post_tags", "ix_wp_post_tags_slug"):
        op.create_index(
            "ix_wp_post_tags_slug",
            "wordpress_post_tags",
            ["tag_slug"],
            unique=False,
        )


def downgrade() -> None:
    if table_exists("wordpress_post_tags"):
        op.drop_table("wordpress_post_tags")
    if table_exists("wordpress_tags"):
        op.drop_table("wordpress_tags")
