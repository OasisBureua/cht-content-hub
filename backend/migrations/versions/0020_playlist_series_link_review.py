"""WPR-6 schema: playlist ↔ series link + human-review queue.

Two schema changes bundled — they're only useful together:

1. `playlist_tags.wp_series_slug` (NEW COLUMN) — nullable FK to
   wordpress_series.slug. Curator-approved link from a YouTube playlist
   (the CH-side canonical identifier for a playlist) to a WordPress
   series (the WP-side authoring taxonomy). Null when unlinked.

2. `playlist_series_match_review` (NEW TABLE) — staging queue for
   fuzzy-match candidates. A match Lambda inserts pending rows with
   scoring signals; a curator (Morgan) approves or rejects. Only
   approved rows write to playlist_tags.wp_series_slug.

Design notes:

- Composite index on (status, created_at) supports the "give me the
  oldest pending reviews" query the admin UI runs.
- `signals` JSONB records the match evidence (doctor overlap set, title
  similarity score, YT playlist title, WP series name) — enough for the
  curator to make an informed decision without re-fetching.
- `reviewed_by` is a free-text tag for now (curator name); the moment we
  have real curator identity via CHT auth, this becomes an FK.
- Approval doesn't cascade back to the review row automatically —
  status flips to 'approved' and the approve endpoint writes the
  playlist_tags update in the same transaction. Rejected rows stay for
  audit ("we already looked at this pair, don't re-suggest").

Revision ID: 0020_playlist_series_link_review
Revises: 0019_wordpress_series_slug_alias
Create Date: 2026-07-29

Note: revision ID shortened from `0020_playlist_series_link_and_review` (36
chars) to `0020_playlist_series_link_review` (32 chars) on 2026-08-03 to fit
alembic's default alembic_version VARCHAR(32) column. The original ID broke
dev deployment when alembic tried to write it into version_num. All prior
migrations (0014-0019) are <=32 chars and applied cleanly.
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

revision: str = "0020_playlist_series_link_review"
down_revision: Union[str, None] = "0019_wordpress_series_slug_alias"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column_name in {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    # 1. Add wp_series_slug to playlist_tags.
    if not _column_exists("playlist_tags", "wp_series_slug"):
        op.add_column(
            "playlist_tags",
            sa.Column("wp_series_slug", sa.String(length=200), nullable=True),
        )
        # FK — nullable so unlinked playlists stay valid. ON DELETE SET NULL
        # so a series tombstone doesn't orphan the playlist row.
        op.create_foreign_key(
            "fk_playlist_tags_wp_series_slug",
            "playlist_tags",
            "wordpress_series",
            ["wp_series_slug"],
            ["slug"],
            ondelete="SET NULL",
        )
    if not index_exists("playlist_tags", "ix_playlist_tags_wp_series_slug"):
        op.create_index(
            "ix_playlist_tags_wp_series_slug",
            "playlist_tags",
            ["wp_series_slug"],
            unique=False,
        )

    # 2. New review queue table.
    if not table_exists("playlist_series_match_review"):
        op.create_table(
            "playlist_series_match_review",
            sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
            sa.Column("youtube_playlist_id", sa.String(length=64), nullable=False),
            sa.Column("wp_series_slug", sa.String(length=200), nullable=False),
            sa.Column("match_score", sa.Float(), nullable=False),
            sa.Column(
                "signals",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default="pending",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reviewed_by", sa.String(length=200), nullable=True),
            # A given (playlist, series) pair should only have one active
            # review row at a time — enforce via unique constraint on the
            # pair when status is 'pending'. Postgres supports partial
            # unique indexes; SQLite tests skip the partial constraint via
            # separate application-layer check.
            sa.UniqueConstraint(
                "youtube_playlist_id",
                "wp_series_slug",
                "status",
                name="uix_playlist_series_review_pair_status",
            ),
        )
    if not index_exists(
        "playlist_series_match_review", "ix_psmr_status_created"
    ):
        op.create_index(
            "ix_psmr_status_created",
            "playlist_series_match_review",
            ["status", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    if table_exists("playlist_series_match_review"):
        op.drop_table("playlist_series_match_review")
    if index_exists("playlist_tags", "ix_playlist_tags_wp_series_slug"):
        op.drop_index("ix_playlist_tags_wp_series_slug", table_name="playlist_tags")
    if _column_exists("playlist_tags", "wp_series_slug"):
        op.drop_constraint(
            "fk_playlist_tags_wp_series_slug",
            "playlist_tags",
            type_="foreignkey",
        )
        op.drop_column("playlist_tags", "wp_series_slug")
