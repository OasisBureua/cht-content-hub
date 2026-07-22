"""Clip model — video/audio content synced from ops-console.

Ported from mediahub to break CHT's dependency on the legacy MediaHub read
path. The 30-column schema is preserved 1:1 so a `pg_dump` of the mediahub
`clips` table can be restored into ContentHub without transformation.

Clips arrive from two pipelines:
- Branded: synced from ops-console via webhook (`source="webhook"`)
- Official: created by channel_sync from platform APIs (`source="direct"`)

The `tags` array powers CHT's biomarker/drug/topic filtering. This is the
field that was silently returning empty on ContentHub before the migration
(clip_post_skipped_models_missing=true in playlist_doctor_tagger).
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from db_types import StringArray


class ClipStatus(str, enum.Enum):
    DRAFT = "draft"
    READY = "ready"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    FAILED = "failed"


class ContentType(str, enum.Enum):
    FULL_PODCAST = "full_podcast"
    CLIP = "clip"


class MediaType(str, enum.Enum):
    VIDEO = "video"
    AUDIO = "audio"


class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    platform: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tags: Mapped[list[str]] = mapped_column(
        StringArray(), nullable=False, default=list, server_default="{}"
    )

    shoot_id: Mapped[str | None] = mapped_column(
        String(255),
        ForeignKey("shoots.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    clip_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[ContentType | None] = mapped_column(
        Enum(ContentType, name="content_type", create_constraint=False),
        nullable=True,
    )
    media_type: Mapped[MediaType | None] = mapped_column(
        Enum(MediaType, name="media_type", create_constraint=False),
        nullable=True,
    )

    status: Mapped[ClipStatus] = mapped_column(
        Enum(ClipStatus, name="clip_status", create_constraint=False),
        default=ClipStatus.DRAFT,
    )
    publish_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    is_short: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    aspect: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    video_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    video_preview_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    thumbnail_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    account_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    privacy: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    channel: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    raw_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    earliest_posted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    ai_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_summary_generated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # SCRUM-75: curator-locked tags. When True, the playlist doctor-tagger
    # (jobs/playlist_doctor_tagger_core.py) skips this row's tag mutation on its
    # daily run — mirrors the kols.curated_fields "sync respects manual lock"
    # pattern from 0011.
    tags_curator_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    shoot = relationship("Shoot", backref="clips", foreign_keys=[shoot_id])

    def __repr__(self) -> str:
        return f"<Clip {self.id}: {self.title}>"
