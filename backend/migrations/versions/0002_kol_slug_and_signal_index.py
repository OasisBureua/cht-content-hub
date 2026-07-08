"""Add kols.slug + composite hcp_signals index for publication queries."""

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

from models.kol import KOL  # noqa: E402
from services.kol_slugs import assign_slugs  # noqa: E402

revision: str = "0002_kol_slug_and_signal_index"
down_revision: Union[str, None] = "0001_contenthub_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _backfill_kol_slugs(connection: sa.Connection) -> None:
    rows = connection.execute(
        sa.text(
            "SELECT id, name FROM kols ORDER BY name ASC"
        )
    ).mappings().all()
    if not rows:
        return
    kols = [KOL(id=row["id"], name=row["name"], slug="pending") for row in rows]
    assign_slugs(kols)
    for kol in kols:
        connection.execute(
            sa.text("UPDATE kols SET slug = :slug WHERE id = :id"),
            {"slug": kol.slug, "id": kol.id},
        )


def upgrade() -> None:
    op.add_column("kols", sa.Column("slug", sa.String(length=128), nullable=True))
    _backfill_kol_slugs(op.get_bind())
    op.alter_column("kols", "slug", nullable=False)
    op.create_index("ix_kols_slug", "kols", ["slug"], unique=True)

    op.create_index(
        "ix_signals_hcp_type_observed",
        "hcp_signals",
        ["hcp_npi", "signal_type", "observed_at"],
        unique=False,
        postgresql_ops={"observed_at": "DESC"},
    )


def downgrade() -> None:
    op.drop_index("ix_signals_hcp_type_observed", table_name="hcp_signals")
    op.drop_index("ix_kols_slug", table_name="kols")
    op.drop_column("kols", "slug")
