"""Merge the two CPR-13 0022 heads.

``0022_shoot_campaign_link`` (report-packet) and
``0022_export_zoom_warehouse`` (Zoom export warehouse) both revised
``0021_wp_tag_namespace_map``. Alembic then has two heads, so
``alembic upgrade head`` fails at API startup.

This empty merge is the single new head. Applying it also applies
whichever 0022 the target DB is missing. The two 0022s do not touch
the same objects (shoots.campaign_id vs export_* tables).

Revision ID must stay ≤32 chars (alembic_version.version_num).

Revision ID: 0023_merge_cpr13_heads
Revises: 0022_shoot_campaign_link, 0022_export_zoom_warehouse
Create Date: 2026-09-24
"""

from __future__ import annotations

from typing import Sequence, Union

revision: str = "0023_merge_cpr13_heads"
down_revision: Union[str, tuple[str, ...], None] = (
    "0022_shoot_campaign_link",
    "0022_export_zoom_warehouse",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
