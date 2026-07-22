"""Post model — platform post w/ engagement metrics, synced from ops-console.

Ported from mediahub. FKs to `clips` and `shoots`. Joined to `clips` at
read time by `/api/public/clips` to attach view/like/comment counts to
each clip response.

Sources:
- "webhook" — branded posts synced from ops-console
- "direct"  — official channel posts fetched directly by MediaHub
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from db_types import StringArray


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint(
            "platform", "provider_post_id", name="uix_posts_platform_provider"
        ),
    )

    id: Mapped[str] = mapped_column(String(255), primary_key=True)

    clip_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("clips.id", ondelete="SET NULL"),
        nullable=True,
    )
    shoot_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("shoots.id", ondelete="SET NULL"),
        nullable=True,
    )

    platform: Mapped[str] = mapped_column(String(50))
    provider_post_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    posted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    content_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_short: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    tags: Mapped[Optional[list[str]]] = mapped_column(StringArray(), nullable=True)
    hashtags: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    mentions: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    media_urls: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    platform_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    source: Mapped[str] = mapped_column(String(20), default="webhook")
    channel: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    # SCRUM-75: curator-locked tags. When True, the playlist doctor-tagger
    # skips this row's tag mutation on its daily run.
    tags_curator_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    view_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    share_count: Mapped[int] = mapped_column(Integer, default=0)
    impression_count: Mapped[int] = mapped_column(Integer, default=0)

    stats_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
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

    clip = relationship("Clip", backref="posts", foreign_keys=[clip_id])
    shoot = relationship("Shoot", backref="posts", foreign_keys=[shoot_id])

    def __repr__(self) -> str:
        return f"<Post {self.id}: {self.platform} - {self.view_count} views>"
