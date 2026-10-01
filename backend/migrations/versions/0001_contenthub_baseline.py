"""Content Hub baseline — KOL + HCP Intel tables.

Revision ID: 0001_contenthub_baseline
Revises:
Create Date: 2026-06-30

Creates all producer-scope tables from ORM models (see docs/kol-hcp-intel-migration.md §4).
PostgreSQL only — partial indexes on feed_subscriptions require PG.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence, Union

from alembic import op

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from path_setup import install  # noqa: E402

install()

import models  # noqa: E402, F401
from database import Base  # noqa: E402

revision: str = "0001_contenthub_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _baseline_tables() -> list:
    # reports.* is created by 0025_reports_schema. The schema does not exist
    # yet, and that revision's DDL (indexes, GIN) is not fully on the ORM.
    return [t for t in Base.metadata.sorted_tables if t.schema != "reports"]


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind, tables=_baseline_tables())


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind, tables=_baseline_tables())
