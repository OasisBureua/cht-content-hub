"""Add youtube_video_id + featured_media_url to wordpress_events.

Both fields are extracted by the mu-plugin on the WordPress side and land
in the payload. Storing them as first-class columns (rather than only in
`raw_payload`) so `/api/public/wordpress` can serve them without JSONB
extraction on every request, and so `youtube_video_id` can be indexed
for CHT's video-clip join.

`youtube_video_id` uses a partial index (WHERE NOT NULL) because most
posts have a value but non-video posts do not — no point paying index
cost for the NULL rows.

Revision ID: 0010_wordpress_events_enrichment
Revises: 0009_clips_and_posts
Create Date: 2026-07-11
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

from migrations.helpers import index_exists  # noqa: E402

revision: str = "0010_wordpress_events_enrichment"
down_revision: Union[str, None] = "0009_clips_and_posts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column_name in {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    if not _column_exists("wordpress_events", "youtube_video_id"):
        op.add_column(
            "wordpress_events",
            sa.Column("youtube_video_id", sa.String(length=20), nullable=True),
        )
    if not _column_exists("wordpress_events", "featured_media_url"):
        op.add_column(
            "wordpress_events",
            sa.Column("featured_media_url", sa.Text(), nullable=True),
        )

    if not index_exists("wordpress_events", "ix_wordpress_events_youtube_video_id"):
        op.create_index(
            "ix_wordpress_events_youtube_video_id",
            "wordpress_events",
            ["youtube_video_id"],
            postgresql_where=sa.text("youtube_video_id IS NOT NULL"),
        )


def downgrade() -> None:
    if index_exists("wordpress_events", "ix_wordpress_events_youtube_video_id"):
        op.drop_index(
            "ix_wordpress_events_youtube_video_id", table_name="wordpress_events"
        )
    if _column_exists("wordpress_events", "featured_media_url"):
        op.drop_column("wordpress_events", "featured_media_url")
    if _column_exists("wordpress_events", "youtube_video_id"):
        op.drop_column("wordpress_events", "youtube_video_id")
