"""Create playlist_tags table — curator-set overlay for YouTube playlists.

Powers the /api/public/playlists endpoint that CHT consumes to render
biomarker-row carousels. Verbatim carry-over from legacy MediaHub schema
(single-table editorial overlay; YouTube metadata joined client-side).

Revision ID: 0007_playlist_tags
Revises: 0006_campaign_platform_data
Create Date: 2026-07-01
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


revision: str = "0007_playlist_tags"
down_revision: Union[str, None] = "0006_campaign_platform_data"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "playlist_tags",
        sa.Column("youtube_playlist_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("lane", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
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
    # Index on lane for /api/public/playlists?lane= queries
    op.create_index("ix_playlist_tags_lane", "playlist_tags", ["lane"])


def downgrade() -> None:
    op.drop_index("ix_playlist_tags_lane", table_name="playlist_tags")
    op.drop_table("playlist_tags")
