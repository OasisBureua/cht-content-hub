"""Add curator-override columns to clips + posts for tag protection.

SCRUM-75: the tagger's daily loop rewrites Clip.tags + Post.tags from
playlist-derived doctor tags. When a curator manually edits tags (via
the new SCRUM-75 admin API), the tagger must respect that lock instead
of clobbering it on the next run. Same "sync respects manual lock"
pattern as `kols.curated_fields` in 0011 (and hcp_match_status).

- `clips.tags_curator_override BOOLEAN NOT NULL DEFAULT FALSE`
- `posts.tags_curator_override BOOLEAN NOT NULL DEFAULT FALSE`

When True, the tagger skips the tag mutation for that row (Shoot.doctors
+ other rows in the same shoot continue to update). PATCH /api/admin/clips/{id}/tags
sets the flag True as part of the edit.

Revision ID: 0012_clip_curator_tag_override
Revises: 0011_kol_admin_fields
Create Date: 2026-07-20
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

revision: str = "0012_clip_curator_tag_override"
down_revision: Union[str, None] = "0011_kol_admin_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("clips", "posts"):
        if not column_exists(table, "tags_curator_override"):
            op.add_column(
                table,
                sa.Column(
                    "tags_curator_override",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("false"),
                ),
            )


def downgrade() -> None:
    for table in ("posts", "clips"):
        if column_exists(table, "tags_curator_override"):
            op.drop_column(table, "tags_curator_override")
