"""CPR-13: shoots.campaign_id — campaign to transcript linkage.

Campaign and Shoot have never had a correlation key, formal or informal.
Campaigns are the reporting unit CHT's report-packet endpoint serves;
Shoot.diarized_transcript is where real transcript text already lives
(synced from ops-console). This column lets an admin link a shoot to the
campaign whose report should include its transcript, without requiring
any change to how shoots are ingested or how campaigns are created.

Nullable, SET NULL on campaign delete, same shape as Shoot's existing
project_id/kol_group_id optional-FK columns.

Revision ID: 0022_shoot_campaign_link
Revises: 0021_wp_tag_namespace_map
Create Date: 2026-09-21
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

revision: str = "0022_shoot_campaign_link"
down_revision: Union[str, None] = "0021_wp_tag_namespace_map"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("shoots", "campaign_id"):
        op.add_column(
            "shoots",
            sa.Column(
                "campaign_id",
                sa.Integer(),
                sa.ForeignKey("campaigns.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    if not index_exists("shoots", "ix_shoots_campaign_id"):
        op.create_index("ix_shoots_campaign_id", "shoots", ["campaign_id"])


def downgrade() -> None:
    op.drop_index("ix_shoots_campaign_id", table_name="shoots")
    op.drop_column("shoots", "campaign_id")
