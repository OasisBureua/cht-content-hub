"""CPR-43: store native survey question schema on export_survey_responses.

Revision ID: 0031_export_survey_questions
Revises: 0030_export_registrations
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from path_setup import install  # noqa: E402

install()

from migrations.helpers import column_exists, table_exists  # noqa: E402

revision: str = "0031_export_survey_questions"
down_revision: Union[str, None] = "0030_export_registrations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("export_survey_responses"):
        return
    if not column_exists("export_survey_responses", "questions"):
        op.add_column(
            "export_survey_responses",
            sa.Column("questions", JSONB(), nullable=True),
        )
    if not column_exists("export_survey_responses", "survey_id"):
        op.add_column(
            "export_survey_responses",
            sa.Column("survey_id", sa.String(length=128), nullable=True),
        )


def downgrade() -> None:
    if not table_exists("export_survey_responses"):
        return
    for col in ("survey_id", "questions"):
        if column_exists("export_survey_responses", col):
            op.drop_column("export_survey_responses", col)
