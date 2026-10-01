"""CPR-14: store jotformFormId from the platform input packet.

source and submission_id already exist on public.export_survey_responses.
This adds the form id the packet now sends beside them.

Revision ID: 0026_survey_jotform_form_id
Revises: 0025_reports_schema
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

revision: str = "0026_survey_jotform_form_id"
down_revision: Union[str, None] = "0025_reports_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("export_survey_responses", "jotform_form_id"):
        op.add_column(
            "export_survey_responses",
            sa.Column("jotform_form_id", sa.String(length=128), nullable=True),
        )
    # Pre-CPR-14 ingest invented submission:{surveyId}:{userId}:{index}
    # and stored source = platform. Re-ingest uses a new key and would
    # insert a second row. The next ingest recreates these from the packet.
    if column_exists("export_survey_responses", "source"):
        op.execute(
            sa.text(
                "DELETE FROM export_survey_responses WHERE source = 'platform'"
            )
        )


def downgrade() -> None:
    if column_exists("export_survey_responses", "jotform_form_id"):
        op.drop_column("export_survey_responses", "jotform_form_id")
