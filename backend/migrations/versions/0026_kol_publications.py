"""UUC-15: kols.publications, a curated list of each KOL's publications.

Each item is ``{title, journal, year, url}``. Written by admins (curated
like bio), shown under the bio on the KOL page.

Revision ID: 0026_kol_publications
Revises: 0025_reports_schema
Create Date: 2026-09-30
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

from migrations.helpers import column_exists  # noqa: E402

revision: str = "0026_kol_publications"
down_revision: Union[str, None] = "0025_reports_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("kols", "publications"):
        op.add_column(
            "kols",
            sa.Column(
                "publications",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
        )


def downgrade() -> None:
    if column_exists("kols", "publications"):
        op.drop_column("kols", "publications")
