"""WordPress Layer 2 projected-state models — CMS mirror read tables.

Distinct from `wordpress_event.WordPressEvent` (Layer 1, append-only event
log). These models are the coalesced, query-optimized projection of what
WordPress looks like *right now*, rebuilt from the event log by the ingest
Lambda inside the same transaction as the Layer 1 insert.

Layers:
  1. `wordpress_events` — every webhook delivery, immutable
  2. `wordpress_posts` + `wordpress_series` + `wordpress_categories` +
     `wordpress_tags` + M:M association tables — Layer 2 projected state
  3. `/api/public/wordpress/*` endpoints — query Layer 2 only

Invariants:
  - Rebuildable: TRUNCATE all Layer 2 tables + replay full event log →
    identical projected state
  - Delete semantics: `wordpress_posts.deleted_at IS NOT NULL` = tombstone.
    Row is preserved so historical joins work; read endpoints filter it out.
  - Term metadata staleness bounded by reconcile cycle (24h) — post events
    can UPSERT a term row with slug-only defaults if we haven't seen the
    term before; the backfill / reconcile Lambda enriches display name,
    description, parent_slug, wp_term_id from WP REST.
  - FK cascade: deleting a term (rare — usually a tombstone) cascades to
    membership rows. Deleting a `wordpress_posts` row cascades to all M:M
    associations for that post. Normal ops never hard-delete either side.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


# ─────────────────────────────────────────────────────────────────────────────
# Term tables — one per taxonomy, identical shape
# ─────────────────────────────────────────────────────────────────────────────


class _TermMixin:
    """Column mixin shared by wordpress_series / _categories / _tags.

    NOT a mapped Base — SQLAlchemy declarative doesn't allow multi-inheritance
    with Base + mixin cleanly for shared columns AND __tablename__. This
    class exists as documentation / linter guide only. Each concrete term
    class re-declares columns explicitly (Ruff-preferred over runtime magic).
    """


class WordPressSeries(Base):
    """WordPress `series` custom taxonomy term (Layer 2)."""

    __tablename__ = "wordpress_series"

    slug: Mapped[str] = mapped_column(String(200), primary_key=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_slug: Mapped[str | None] = mapped_column(String(200), nullable=True)
    wp_term_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class WordPressCategory(Base):
    """WordPress native `category` taxonomy term (Layer 2)."""

    __tablename__ = "wordpress_categories"

    slug: Mapped[str] = mapped_column(String(200), primary_key=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_slug: Mapped[str | None] = mapped_column(String(200), nullable=True)
    wp_term_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class WordPressTag(Base):
    """WordPress native `post_tag` taxonomy term (Layer 2)."""

    __tablename__ = "wordpress_tags"

    slug: Mapped[str] = mapped_column(String(200), primary_key=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_slug: Mapped[str | None] = mapped_column(String(200), nullable=True)
    wp_term_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ─────────────────────────────────────────────────────────────────────────────
# Post table — coalesced current state
# ─────────────────────────────────────────────────────────────────────────────


class WordPressPost(Base):
    """Coalesced current state of one WordPress post_id.

    One row per post_id, ever. Deletions set `deleted_at` — the row itself
    persists so historical joins on association tables remain valid.
    """

    __tablename__ = "wordpress_posts"

    post_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_type: Mapped[str] = mapped_column(String(64), nullable=False)
    slug: Mapped[str] = mapped_column(String(500), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    permalink: Mapped[str] = mapped_column(String(1000), nullable=False)
    modified_gmt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    youtube_video_id: Mapped[str | None] = mapped_column(
        String(20), nullable=True, index=True
    )
    featured_media_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # References the wordpress_events.id that this projected state came from.
    # Not a formal FK (event rows are append-only, never deleted, so the
    # reference is safe without engine-level enforcement — and skipping the
    # FK avoids the cross-layer coupling that would prevent Layer 1 from
    # being archived independently).
    last_event_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# Association tables (M:M)
# ─────────────────────────────────────────────────────────────────────────────


class WordPressPostSeries(Base):
    """Post ↔ series membership. Composite PK enforces uniqueness."""

    __tablename__ = "wordpress_post_series"

    post_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("wordpress_posts.post_id", ondelete="CASCADE"),
        nullable=False,
    )
    series_slug: Mapped[str] = mapped_column(
        String(200),
        ForeignKey("wordpress_series.slug", ondelete="CASCADE"),
        nullable=False,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        PrimaryKeyConstraint("post_id", "series_slug"),
    )


class WordPressPostCategory(Base):
    """Post ↔ category membership."""

    __tablename__ = "wordpress_post_categories"

    post_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("wordpress_posts.post_id", ondelete="CASCADE"),
        nullable=False,
    )
    category_slug: Mapped[str] = mapped_column(
        String(200),
        ForeignKey("wordpress_categories.slug", ondelete="CASCADE"),
        nullable=False,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        PrimaryKeyConstraint("post_id", "category_slug"),
    )


class WordPressPostTag(Base):
    """Post ↔ tag membership."""

    __tablename__ = "wordpress_post_tags"

    post_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("wordpress_posts.post_id", ondelete="CASCADE"),
        nullable=False,
    )
    tag_slug: Mapped[str] = mapped_column(
        String(200),
        ForeignKey("wordpress_tags.slug", ondelete="CASCADE"),
        nullable=False,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        PrimaryKeyConstraint("post_id", "tag_slug"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Series slug alias table (WPR-8)
# ─────────────────────────────────────────────────────────────────────────────


class WordPressSeriesSlugAlias(Base):
    """Historical slug → current slug redirect for renamed series.

    When Andrew renames a series in wp-admin, the term_updated event
    projection detects the rename (matching wp_term_id, differing slug),
    inserts an alias row for the OLD slug, updates the wordpress_series
    row's slug to the NEW slug, and moves M:M memberships across.

    CHT playlist-detail routes catch requests for the old slug, look up
    the alias, and 301 redirect to the current slug.
    """

    __tablename__ = "wordpress_series_slug_alias"

    old_slug: Mapped[str] = mapped_column(String(200), primary_key=True)
    current_slug: Mapped[str] = mapped_column(
        String(200),
        ForeignKey("wordpress_series.slug", ondelete="CASCADE"),
        nullable=False,
    )
    renamed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
