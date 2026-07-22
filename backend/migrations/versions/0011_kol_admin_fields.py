"""Add admin-editable + curated-override columns to kols.

Adds three columns to support the SCRUM-58 KOL admin surface:

- `display_order INTEGER NULL` — admin-controlled sort override. NULL = default
  alphabetical/facet order. Non-NULL rows sort ahead of NULL rows, low-to-high.
- `featured BOOLEAN NOT NULL DEFAULT FALSE` — flag for the "featured KOLs"
  surface on public + app KOL pages.
- `curated_fields JSONB NOT NULL DEFAULT '[]'` — array of field names an admin
  has manually curated. Enrichment sync jobs consult this list before
  overwriting a field (see `hcp_match_status` precedent at
  hcp_intel/openalex_backfill.py:103 for the same "sync respects manual lock"
  pattern already in the codebase).

`display_order` gets a partial index (WHERE NOT NULL) so ordered-list queries
skip the mass of NULL rows. Same shape as
`ix_wordpress_events_youtube_video_id` in 0010.

Revision ID: 0011_kol_admin_fields
Revises: 0010_wordpress_events_enrichment
Create Date: 2026-07-15
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

from migrations.helpers import column_exists, index_exists  # noqa: E402

revision: str = "0011_kol_admin_fields"
down_revision: Union[str, None] = "0010_wordpress_events_enrichment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("kols", "display_order"):
        op.add_column(
            "kols",
            sa.Column("display_order", sa.Integer(), nullable=True),
        )
    if not column_exists("kols", "featured"):
        op.add_column(
            "kols",
            sa.Column(
                "featured",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if not column_exists("kols", "curated_fields"):
        # Postgres path — production. SQLite fallback in tests uses JSON
        # (registered in db_types) which accepts the same server_default text.
        op.add_column(
            "kols",
            sa.Column(
                "curated_fields",
                sa.JSON().with_variant(
                    sa.dialects.postgresql.JSONB(), "postgresql"
                ),
                nullable=False,
                server_default=sa.text("'[]'::jsonb")
                if op.get_bind().dialect.name == "postgresql"
                else sa.text("'[]'"),
            ),
        )

    if not index_exists("kols", "ix_kols_display_order"):
        op.create_index(
            "ix_kols_display_order",
            "kols",
            ["display_order"],
            postgresql_where=sa.text("display_order IS NOT NULL"),
        )
    if not index_exists("kols", "ix_kols_featured"):
        op.create_index(
            "ix_kols_featured",
            "kols",
            ["featured"],
            postgresql_where=sa.text("featured = true"),
        )


def downgrade() -> None:
    if index_exists("kols", "ix_kols_featured"):
        op.drop_index("ix_kols_featured", table_name="kols")
    if index_exists("kols", "ix_kols_display_order"):
        op.drop_index("ix_kols_display_order", table_name="kols")
    if column_exists("kols", "curated_fields"):
        op.drop_column("kols", "curated_fields")
    if column_exists("kols", "featured"):
        op.drop_column("kols", "featured")
    if column_exists("kols", "display_order"):
        op.drop_column("kols", "display_order")
