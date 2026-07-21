"""ORM models for tagger observability (SCRUM-78).

Populated by jobs.tagger_observability.record_run(); read by
admin/tagger.py to surface recent runs + tag diffs to curators.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class TaggerRun(Base):
    __tablename__ = "tagger_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    dry_run: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    shoots_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    shoots_doctors_corrected: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    clips_changed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    posts_changed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    clips_curator_locked_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    posts_curator_locked_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    orphaned_404_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    api_error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    clip_post_skipped_models_missing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


class TagDiffRow(Base):
    __tablename__ = "tag_diffs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tagger_runs.id"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    shoot_id: Mapped[str] = mapped_column(String(255), nullable=False)
    shoot_name: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    provider_post_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_tags: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
    )
    after_tags: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
