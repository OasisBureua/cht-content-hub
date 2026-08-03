"""WP tag → namespaced tag projection map (WPR-11).

Lookup table used at ingest time to project flat WordPress tag slugs onto
ContentHub's namespaced tag vocabulary (biomarker, drug, trial, conference,
topic, stage). Unmapped tags fall back to `wp:<slug>` — never lost.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class WpTagNamespaceMap(Base):
    """Curator + rule-driven mapping from WP tag slug → namespaced tag."""

    __tablename__ = "wp_tag_namespace_map"

    wp_tag_slug: Mapped[str] = mapped_column(String(200), primary_key=True)
    canonical_namespace: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    canonical_value: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="rule", server_default="rule"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
