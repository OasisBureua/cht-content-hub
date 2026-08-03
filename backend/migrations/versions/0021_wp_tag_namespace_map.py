"""WPR-11: wp_tag_namespace_map — flat WP tags → namespaced projection.

WordPress uses flat single-token tag slugs (esr1, t-dxd, destiny-breast-09).
ContentHub uses namespaced tags (biomarker:ESR1, drug:T-DXd, trial:DESTINY-Breast-09).
This table bridges the two vocabularies at ingest time.

For each WP tag slug we ingest, the projection layer consults this map:
- Row present → project to `canonical_namespace:canonical_value`
- Row absent → fallback to `wp:<slug>` (never lose a tag)

Auto-fallback means the projection layer never fails on unmapped tags,
and new WP tags Andrew adds surface as `wp:*` immediately without breaking
CHT filter surfaces. A follow-up curator pass can then promote them into
their proper namespace.

Design notes:
- `wp_tag_slug` is the primary key (verbatim WP form, lowercase).
- `canonical_namespace` is one of the fixed namespaces (biomarker, drug,
  trial, conference, topic, stage) — no free-form values (that's what
  the `wp:` fallback is for).
- `canonical_value` is the display-form value (may contain uppercase,
  hyphens, plus signs — e.g. `HER2+`, `T-DXd`, `DESTINY-Breast-09`).
- `source` records how the row got created — `rule` (auto-generated via
  seed rulebook), `curator` (manually approved), `auto_wp_fallback`
  (placeholder — should never actually be stored, tracked here for
  future flexibility).

Revision ID: 0021_wp_tag_namespace_map
Revises: 0020_playlist_series_link_and_review
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

revision: str = "0021_wp_tag_namespace_map"
down_revision: Union[str, None] = "0020_playlist_series_link_review"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("wp_tag_namespace_map"):
        op.create_table(
            "wp_tag_namespace_map",
            sa.Column("wp_tag_slug", sa.String(length=200), primary_key=True),
            sa.Column(
                "canonical_namespace", sa.String(length=50), nullable=False
            ),
            sa.Column(
                "canonical_value", sa.String(length=200), nullable=False
            ),
            sa.Column(
                "source",
                sa.String(length=32),
                nullable=False,
                server_default="rule",
            ),
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
    if not index_exists(
        "wp_tag_namespace_map", "ix_wp_tag_namespace_map_namespace"
    ):
        op.create_index(
            "ix_wp_tag_namespace_map_namespace",
            "wp_tag_namespace_map",
            ["canonical_namespace"],
            unique=False,
        )


def downgrade() -> None:
    if table_exists("wp_tag_namespace_map"):
        op.drop_table("wp_tag_namespace_map")
