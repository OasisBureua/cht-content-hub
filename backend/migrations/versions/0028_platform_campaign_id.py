"""CPR-13: store the platform campaign id used by scheduled export ingest.

The daily job calls
GET /api/export/reports/campaigns/{Program.campaignId}/input-packet.
This column is an optional AZ-style override. Blank rows use Hub campaigns.id.

Revision ID: 0028_platform_campaign_id
Revises: 0027_survey_jotform_form_id
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

from migrations.helpers import column_exists  # noqa: E402

revision: str = "0028_platform_campaign_id"
down_revision: Union[str, None] = "0027_survey_jotform_form_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("campaigns", "platform_campaign_id"):
        op.add_column(
            "campaigns",
            sa.Column("platform_campaign_id", sa.String(length=128), nullable=True),
        )


def downgrade() -> None:
    if column_exists("campaigns", "platform_campaign_id"):
        op.drop_column("campaigns", "platform_campaign_id")
