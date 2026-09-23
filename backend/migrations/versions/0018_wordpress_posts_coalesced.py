"""Add wordpress_posts — Layer 2 coalesced current-state per WP post.

WPR-2 Sub-unit B (posts). This is the projected read table that supersedes
per-request coalescing of `wordpress_events` via DISTINCT ON.

Design choices:

- **`post_id` is the primary key** — one row per WP post_id, ever. Deletions
  mark `deleted_at` rather than removing the row, so historical joins
  (e.g., "posts assigned to a deleted series last month") still work.
- **`deleted_at IS NOT NULL`** is the delete-tombstone convention. Read
  endpoints filter to `deleted_at IS NULL` for the live editorial view.
- **`last_event_id`** references the source `wordpress_events.id` that this
  row was projected from. Enables audit ("which webhook wrote this?") and
  reprojection ("replay all events with id > X").
- **`modified_gmt` is preserved** as the WP editorial timestamp — separate
  from `updated_at` which tracks the ContentHub-side projection write time.
- **Content fields** (slug, title, status, permalink, youtube_video_id,
  featured_media_url) are duplicated here for read performance. This is
  denormalization against `wordpress_events` — deliberate — the event log
  stays authoritative for history, this table optimizes for "what does
  post X look like right now."

Revision ID: 0018_wordpress_posts_coalesced
Revises: 0017_wordpress_tags_terms
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

revision: str = "0018_wordpress_posts_coalesced"
down_revision: Union[str, None] = "0017_wordpress_tags_terms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("wordpress_posts"):
        op.create_table(
            "wordpress_posts",
            sa.Column("post_id", sa.Integer(), primary_key=True),
            sa.Column("post_type", sa.String(length=64), nullable=False),
            sa.Column("slug", sa.String(length=500), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("permalink", sa.String(length=1000), nullable=False),
            sa.Column(
                "modified_gmt", sa.DateTime(timezone=True), nullable=False
            ),
            sa.Column("youtube_video_id", sa.String(length=20), nullable=True),
            sa.Column("featured_media_url", sa.Text(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_event_id", sa.BigInteger(), nullable=False),
            sa.Column(
                "first_seen",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
    if not index_exists("wordpress_posts", "ix_wordpress_posts_modified_gmt"):
        op.create_index(
            "ix_wordpress_posts_modified_gmt",
            "wordpress_posts",
            ["modified_gmt"],
            unique=False,
        )
    if not index_exists("wordpress_posts", "ix_wordpress_posts_deleted_at"):
        op.create_index(
            "ix_wordpress_posts_deleted_at",
            "wordpress_posts",
            ["deleted_at"],
            unique=False,
        )
    if not index_exists("wordpress_posts", "ix_wordpress_posts_youtube_video_id"):
        op.create_index(
            "ix_wordpress_posts_youtube_video_id",
            "wordpress_posts",
            ["youtube_video_id"],
            unique=False,
        )

    # Retroactive FK from the M:M tables to wordpress_posts.post_id. These
    # constraints were deliberately deferred out of 0015-0017 because the
    # parent table didn't exist yet — this migration closes that loop.
    #
    # ON DELETE CASCADE mirrors the parent-side cleanup: if we ever hard-
    # delete a wordpress_posts row (we won't in normal ops — we use the
    # deleted_at tombstone) the association rows follow. Cascade is the
    # safe default: leaving orphan (post_id, term_slug) rows in the
    # association tables would violate the invariant that every association
    # references a known post.
    op.create_foreign_key(
        "fk_wp_post_series_post_id",
        "wordpress_post_series",
        "wordpress_posts",
        ["post_id"],
        ["post_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_wp_post_categories_post_id",
        "wordpress_post_categories",
        "wordpress_posts",
        ["post_id"],
        ["post_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_wp_post_tags_post_id",
        "wordpress_post_tags",
        "wordpress_posts",
        ["post_id"],
        ["post_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_wp_post_tags_post_id", "wordpress_post_tags", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_wp_post_categories_post_id",
        "wordpress_post_categories",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_wp_post_series_post_id",
        "wordpress_post_series",
        type_="foreignkey",
    )
    if table_exists("wordpress_posts"):
        op.drop_table("wordpress_posts")
