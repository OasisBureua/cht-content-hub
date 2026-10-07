"""CPR-45: KOLs attached to a campaign by an admin.

Zoom-based campaigns have no shoots, so the report packet had no Hub KOLs for
them. campaign_kols lets an admin attach KOLs directly.

Revision ID: 0029_campaign_kols
Revises: 0028_platform_campaign_id
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

from migrations.helpers import table_exists  # noqa: E402

revision: str = "0029_campaign_kols"
down_revision: Union[str, None] = "0028_platform_campaign_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("campaign_kols"):
        return
    op.create_table(
        "campaign_kols",
        sa.Column(
            "campaign_id",
            sa.Integer(),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "kol_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("kols.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )
    op.create_index("ix_campaign_kols_kol_id", "campaign_kols", ["kol_id"])


def downgrade() -> None:
    if table_exists("campaign_kols"):
        op.drop_index("ix_campaign_kols_kol_id", table_name="campaign_kols")
        op.drop_table("campaign_kols")
