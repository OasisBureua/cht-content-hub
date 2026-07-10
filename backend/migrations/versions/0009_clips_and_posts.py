"""Create clips + posts tables — mediahub decoupling for CHT clip consumption.

Ports the 30-column `clips` and 27-column `posts` schemas from mediahub
verbatim so pg_dump/pg_restore can carry 3,155 clips + ~2,300 posts across
without transformation. Both tables FK to `shoots` (already present in
contenthub via SCRUM-39). `posts.clip_id` FKs to `clips.id`.

Enums (`clip_status`, `content_type`, `media_type`) use `create_constraint=False`
in the ORM but Alembic still creates the PG ENUM types — matching mediahub.

Revision ID: 0009_clips_and_posts
Revises: 0008_wordpress_events
Create Date: 2026-07-10
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

from migrations.helpers import index_exists, table_exists  # noqa: E402

revision: str = "0009_clips_and_posts"
down_revision: Union[str, None] = "0008_wordpress_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CLIP_STATUS_VALUES = ("DRAFT", "READY", "SCHEDULED", "PUBLISHED", "FAILED")


def upgrade() -> None:
    # Match mediahub prod: `clip_status` is a PG ENUM with UPPERCASE labels.
    # SQLAlchemy stores Python Enum instances by name (e.g. ClipStatus.DRAFT.name = "DRAFT").
    # `CREATE TYPE IF NOT EXISTS` isn't supported until PG16 — use a DO block.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'clip_status') THEN
                CREATE TYPE clip_status AS ENUM ('DRAFT', 'READY', 'SCHEDULED', 'PUBLISHED', 'FAILED');
            END IF;
        END
        $$;
        """
    )

    if not table_exists("clips"):
        op.create_table(
            "clips",
            sa.Column("id", sa.String(length=255), primary_key=True),
            sa.Column("title", sa.String(length=500), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("platform", sa.String(length=50), nullable=True),
            sa.Column(
                "tags",
                postgresql.ARRAY(sa.String()),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "shoot_id",
                sa.String(length=255),
                sa.ForeignKey("shoots.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("clip_number", sa.Integer(), nullable=True),
            sa.Column("content_type", sa.String(length=50), nullable=True),
            sa.Column("media_type", sa.String(length=50), nullable=True),
            sa.Column(
                "status",
                postgresql.ENUM(
                    *_CLIP_STATUS_VALUES,
                    name="clip_status",
                    create_type=False,  # created above via DO block
                ),
                nullable=False,
                server_default="DRAFT",
            ),
            sa.Column("publish_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_short", sa.Boolean(), nullable=True),
            sa.Column("aspect", sa.String(length=20), nullable=True),
            sa.Column("video_path", sa.String(length=1000), nullable=True),
            sa.Column("video_preview_url", sa.String(length=1000), nullable=True),
            sa.Column("thumbnail_path", sa.String(length=1000), nullable=True),
            sa.Column("duration_seconds", sa.Integer(), nullable=True),
            sa.Column("account_id", sa.String(length=255), nullable=True),
            sa.Column("privacy", sa.String(length=50), nullable=True),
            sa.Column("channel", sa.String(length=100), nullable=True),
            sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("earliest_posted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ai_summary", sa.Text(), nullable=True),
            sa.Column("ai_summary_generated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "synced_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
    if not index_exists("clips", "ix_clips_shoot_id"):
        op.create_index("ix_clips_shoot_id", "clips", ["shoot_id"])
    if not index_exists("clips", "ix_clips_channel"):
        op.create_index("ix_clips_channel", "clips", ["channel"])

    if not table_exists("posts"):
        op.create_table(
            "posts",
            sa.Column("id", sa.String(length=255), primary_key=True),
            sa.Column(
                "clip_id",
                sa.String(length=255),
                sa.ForeignKey("clips.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "shoot_id",
                sa.String(length=255),
                sa.ForeignKey("shoots.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("platform", sa.String(length=50), nullable=False),
            sa.Column("provider_post_id", sa.String(length=255), nullable=True),
            sa.Column("title", sa.String(length=500), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("thumbnail_url", sa.String(length=1000), nullable=True),
            sa.Column("content_url", sa.String(length=1000), nullable=True),
            sa.Column("content_type", sa.String(length=50), nullable=True),
            sa.Column("duration_seconds", sa.Integer(), nullable=True),
            sa.Column("is_short", sa.Boolean(), nullable=True),
            sa.Column("language", sa.String(length=10), nullable=True),
            sa.Column("tags", postgresql.ARRAY(sa.String()), nullable=True),
            sa.Column("hashtags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("mentions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("media_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column(
                "platform_metadata",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
            ),
            sa.Column(
                "source", sa.String(length=20), nullable=False, server_default="webhook"
            ),
            sa.Column("channel", sa.String(length=100), nullable=True),
            sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("like_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("comment_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("share_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "impression_count", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("stats_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "synced_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "platform", "provider_post_id", name="uix_posts_platform_provider"
            ),
        )
    if not index_exists("posts", "ix_posts_channel"):
        op.create_index("ix_posts_channel", "posts", ["channel"])
    if not index_exists("posts", "ix_posts_clip_id"):
        op.create_index("ix_posts_clip_id", "posts", ["clip_id"])
    if not index_exists("posts", "ix_posts_shoot_id"):
        op.create_index("ix_posts_shoot_id", "posts", ["shoot_id"])
    # Matches mediahub prod: GIN index on posts.tags for fast ARRAY .any() lookups.
    if not index_exists("posts", "ix_posts_tags"):
        op.create_index(
            "ix_posts_tags", "posts", ["tags"], postgresql_using="gin"
        )


def downgrade() -> None:
    op.drop_index("ix_posts_tags", table_name="posts")
    op.drop_index("ix_posts_shoot_id", table_name="posts")
    op.drop_index("ix_posts_clip_id", table_name="posts")
    op.drop_index("ix_posts_channel", table_name="posts")
    op.drop_table("posts")
    op.drop_index("ix_clips_channel", table_name="clips")
    op.drop_index("ix_clips_shoot_id", table_name="clips")
    op.drop_table("clips")
    op.execute("DROP TYPE IF EXISTS clip_status")
