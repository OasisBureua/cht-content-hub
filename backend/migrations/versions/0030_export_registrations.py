"""CPR-42: export_registrations + attendance profile/user columns.

Revision ID: 0030_export_registrations
Revises: 0029_campaign_kols
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

from migrations.helpers import column_exists, index_exists, table_exists  # noqa: E402

revision: str = "0030_export_registrations"
down_revision: Union[str, None] = "0029_campaign_kols"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("export_registrations"):
        op.create_table(
            "export_registrations",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("dedupe_key", sa.String(length=512), nullable=False),
            sa.Column("platform_tool_program_id", sa.String(length=64), nullable=False),
            sa.Column("campaign_id", sa.Integer(), nullable=True),
            sa.Column("user_id", sa.String(length=64), nullable=False),
            sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(length=64), nullable=False),
            sa.Column("specialty", sa.String(length=255), nullable=True),
            sa.Column("institution", sa.String(length=500), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["campaign_id"],
                ["campaigns.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["platform_tool_program_id"],
                ["export_sessions.platform_tool_program_id"],
                name="fk_export_registrations_program",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "dedupe_key", name="uix_export_registrations_dedupe_key"
            ),
        )
    if table_exists("export_registrations"):
        if not index_exists("export_registrations", "ix_export_registrations_program"):
            op.create_index(
                "ix_export_registrations_program",
                "export_registrations",
                ["platform_tool_program_id"],
            )
        if not index_exists("export_registrations", "ix_export_registrations_campaign"):
            op.create_index(
                "ix_export_registrations_campaign",
                "export_registrations",
                ["campaign_id"],
            )
        if not index_exists("export_registrations", "ix_export_registrations_user"):
            op.create_index(
                "ix_export_registrations_user",
                "export_registrations",
                ["user_id"],
            )

    if table_exists("export_attendance_events"):
        if not column_exists("export_attendance_events", "user_id"):
            op.add_column(
                "export_attendance_events",
                sa.Column("user_id", sa.String(length=64), nullable=True),
            )
        if not column_exists("export_attendance_events", "specialty"):
            op.add_column(
                "export_attendance_events",
                sa.Column("specialty", sa.String(length=255), nullable=True),
            )
        if not column_exists("export_attendance_events", "institution"):
            op.add_column(
                "export_attendance_events",
                sa.Column("institution", sa.String(length=500), nullable=True),
            )
        if not index_exists(
            "export_attendance_events", "ix_export_attendance_events_user_id"
        ):
            op.create_index(
                "ix_export_attendance_events_user_id",
                "export_attendance_events",
                ["user_id"],
            )


def downgrade() -> None:
    if table_exists("export_attendance_events"):
        if index_exists(
            "export_attendance_events", "ix_export_attendance_events_user_id"
        ):
            op.drop_index(
                "ix_export_attendance_events_user_id",
                table_name="export_attendance_events",
            )
        for col in ("institution", "specialty", "user_id"):
            if column_exists("export_attendance_events", col):
                op.drop_column("export_attendance_events", col)
    if table_exists("export_registrations"):
        op.drop_table("export_registrations")
