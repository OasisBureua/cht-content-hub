"""PlaylistTag model — curator-set overlay for YouTube playlists.

The full playlist metadata (title, videos, description) is fetched live
from the YouTube Data API by the /api/public/playlists endpoint. This
table only stores the curator-set tags + editorial lane that aren't
available from YouTube itself.

Powers the /api/public/playlists endpoint's `?tag=` and `?lane=` filters,
which CHT consumes to render biomarker-row carousels (replacing the
brittle frontend `_generated-catalog-playlists.json` fuzzy-title-match
approach).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from db_types import StringArray


class PlaylistTag(Base):
    """Curator-set tag overlay for a YouTube playlist."""

    __tablename__ = "playlist_tags"

    youtube_playlist_id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Namespaced tags, same vocabulary as content tags:
    # biomarker:HER2+, drug:T-DXd, trial:DESTINY-Breast09, etc.
    # StringArray = PostgreSQL text[] in prod (supports `.any()` in queries),
    # JSON in SQLite tests. See db_types.StringArray.
    tags: Mapped[list[str]] = mapped_column(
        StringArray(), nullable=False, default=list, server_default="{}"
    )

    # Editorial lane — high-level grouping. CHT surfaces playlists by
    # lane (e.g. all `biomarker`-lane playlists in the public catalog).
    # Values: biomarker | drug | trial | doctor_pair | mixed | archive
    lane: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
