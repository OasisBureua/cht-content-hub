"""CPR-25: report_templates.semver + s3_key — catalog pointer to S3 template.

The template body (system prompt + HTML skeleton) lives in the cht-reports
bucket under ``templates/{type}/{semver}/``. Hub only stores the pointer so
the report worker can resolve which version to load at generate time.

Both columns are nullable: rows created before this migration (admin
"analytics" templates) have no S3 body. One row per (type, semver).

Revision ID: 0024_report_template_pointer
Revises: 0023_merge_cpr13_heads
Create Date: 2026-09-25
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

revision: str = "0024_report_template_pointer"
down_revision: Union[str, None] = "0023_merge_cpr13_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("report_templates", "semver"):
        op.add_column(
            "report_templates", sa.Column("semver", sa.String(length=32), nullable=True)
        )
    if not column_exists("report_templates", "s3_key"):
        op.add_column(
            "report_templates", sa.Column("s3_key", sa.String(length=500), nullable=True)
        )
    if not index_exists("report_templates", "uix_report_templates_type_semver"):
        op.create_index(
            "uix_report_templates_type_semver",
            "report_templates",
            ["type", "semver"],
            unique=True,
        )


def downgrade() -> None:
    op.drop_index("uix_report_templates_type_semver", table_name="report_templates")
    op.drop_column("report_templates", "s3_key")
    op.drop_column("report_templates", "semver")
