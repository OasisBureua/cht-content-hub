"""WPR-6 review queue: fuzzy-match candidates for playlist ↔ series links.

The fuzzy-match Lambda scores existing YouTube playlists against
wordpress_series terms and inserts pending rows here — one row per
(playlist, series) candidate pair. A curator (Morgan) reviews each
pending row and approves or rejects.

On approval, `playlist_tags.wp_series_slug` is set to the linked series
in the same transaction, and the review row's status flips to 'approved'.

On rejection, the row stays as an audit trail so the fuzzy-match Lambda
doesn't re-suggest the same pair.

Status values:
  - `pending`  — waiting for curator review (default on insert)
  - `approved` — curator approved; playlist_tags updated
  - `rejected` — curator rejected; do not re-suggest
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    Integer as sa_Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class PlaylistSeriesMatchReview(Base):
    """Staging queue for fuzzy-matched playlist ↔ series pair suggestions."""

    __tablename__ = "playlist_series_match_review"
    __table_args__ = (
        UniqueConstraint(
            "youtube_playlist_id",
            "wp_series_slug",
            "status",
            name="uix_playlist_series_review_pair_status",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(sa_Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    youtube_playlist_id: Mapped[str] = mapped_column(String(64), nullable=False)
    wp_series_slug: Mapped[str] = mapped_column(String(200), nullable=False)
    match_score: Mapped[float] = mapped_column(Float, nullable=False)

    # Explanation blob: {doctor_overlap: [...], title_similarity: 0.87,
    # yt_title: "...", wp_name: "..."} — everything the curator needs to
    # decide without re-fetching. Kept as JSONB for open evolution.
    signals: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
