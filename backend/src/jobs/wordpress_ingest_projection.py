"""Projection layer — writes WordPress webhook events to Layer 2.

The Layer 1 write (wordpress_events) captures the raw event; this module
projects that event onto the coalesced current-state tables
(wordpress_posts + wordpress_series + wordpress_categories + wordpress_tags
+ their M:M association tables).

Called from `handler._insert_event` inside the same DB transaction as the
Layer 1 insert. If projection fails, the transaction rolls back and SQS
redelivers — the event log stays consistent with the projection.

Two entry points:
  - `project_post_event(db, payload)` — handles published / updated / deleted
    events from post webhooks. Idempotent by construction (UPSERT semantics).
  - `project_term_event(db, payload)` — handles term_updated / term_deleted
    events from mu-plugin v0.6 taxonomy webhooks.

Design notes:
  - **UPSERT terms on post-event ingest**: if a post arrives referencing a
    series slug we haven't seen, insert it with slug-as-name defaults so
    the FK constraint on the association table is satisfied. The reconcile
    Lambda / backfill enriches display name later. Trade-off: temporary
    ugly UI vs. dropping the association entirely. We chose completeness.
  - **Association reconcile is set-based**: for each post event, compute
    the target set of series/category/tag slugs, delete rows in the
    association that aren't in the target set, insert rows that are missing.
    This handles both additions and removals in one pass and is idempotent.
  - **Delete = tombstone**: `wordpress_posts.deleted_at = now()`. Membership
    rows are left alone — they FK to `wordpress_posts.post_id`, and the
    read endpoints filter posts by `deleted_at IS NULL`, so a deleted post's
    memberships become invisible even though the rows still exist. This
    preserves history for reconcile queries ("posts deleted this week").
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession


# ─────────────────────────────────────────────────────────────────────────────
# Post-event projection
# ─────────────────────────────────────────────────────────────────────────────


async def project_post_event(
    db: AsyncSession, payload: dict[str, Any], event_id: int
) -> None:
    """Project one wordpress_events row into Layer 2.

    Args:
        db: Active AsyncSession — must be the same session that inserted
            the Layer 1 event (transaction shared).
        payload: The webhook payload (already validated by the router).
        event_id: `wordpress_events.id` of the row this projection follows.

    Behavior by event type:
        - `published` or `updated`: UPSERT wordpress_posts, UPSERT any
          referenced terms with slug-only defaults, reconcile M:M associations.
        - `deleted`: mark wordpress_posts.deleted_at, leave associations
          in place (tombstone pattern).

    Idempotent: replay of the same event produces zero net change.
    """
    from models.wordpress_projection import (
        WordPressCategory,
        WordPressPost,
        WordPressPostCategory,
        WordPressPostSeries,
        WordPressPostTag,
        WordPressSeries,
        WordPressTag,
    )

    event = payload["event"]
    post_id = int(payload["post_id"])

    if event == "deleted":
        await _mark_post_deleted(db, post_id, event_id)
        return

    # published or updated
    await _upsert_post(db, payload, event_id)

    # UPSERT term rows for any slug we reference. Slug-only entries are
    # placeholder-quality — the reconcile/backfill Lambda enriches them
    # with real name/description/parent from WP REST later.
    await _upsert_terms(
        db, WordPressSeries, payload.get("series") or []
    )
    await _upsert_terms(
        db, WordPressCategory, payload.get("categories") or []
    )
    await _upsert_terms(
        db, WordPressTag, payload.get("tags") or []
    )

    # Reconcile M:M associations to match the payload's target set.
    await _reconcile_membership(
        db,
        assoc_model=WordPressPostSeries,
        slug_column="series_slug",
        post_id=post_id,
        target_slugs=payload.get("series") or [],
    )
    await _reconcile_membership(
        db,
        assoc_model=WordPressPostCategory,
        slug_column="category_slug",
        post_id=post_id,
        target_slugs=payload.get("categories") or [],
    )
    await _reconcile_membership(
        db,
        assoc_model=WordPressPostTag,
        slug_column="tag_slug",
        post_id=post_id,
        target_slugs=payload.get("tags") or [],
    )


async def _upsert_post(
    db: AsyncSession, payload: dict[str, Any], event_id: int
) -> None:
    """INSERT or UPDATE the wordpress_posts row for this post_id.

    Uses SELECT + branch rather than dialect-specific ON CONFLICT so the
    same code works against SQLite (tests) and Postgres (prod).
    """
    from models.wordpress_projection import WordPressPost

    post_id = int(payload["post_id"])
    modified_gmt = _parse_modified_gmt(payload["modified_gmt"])
    now = datetime.now(timezone.utc)

    existing = (
        await db.execute(
            select(WordPressPost).where(WordPressPost.post_id == post_id)
        )
    ).scalar_one_or_none()

    if existing is None:
        db.add(
            WordPressPost(
                post_id=post_id,
                post_type=payload["post_type"],
                slug=payload["slug"],
                title=payload["title"],
                status=payload["status"],
                permalink=payload["permalink"],
                modified_gmt=modified_gmt,
                youtube_video_id=payload.get("youtube_video_id"),
                featured_media_url=payload.get("featured_media_url"),
                deleted_at=None,
                last_event_id=event_id,
            )
        )
    else:
        # Only overwrite if this event is newer than what we have. Guards
        # against out-of-order webhook delivery (SQS batching / retry).
        # SQLite returns naive datetimes from TIMESTAMP columns even when
        # the ORM declared them tz-aware; coerce to UTC for the compare so
        # the same code works on Postgres (already tz-aware) and SQLite.
        existing_mgmt = _ensure_utc(existing.modified_gmt)
        if modified_gmt >= existing_mgmt:
            existing.post_type = payload["post_type"]
            existing.slug = payload["slug"]
            existing.title = payload["title"]
            existing.status = payload["status"]
            existing.permalink = payload["permalink"]
            existing.modified_gmt = modified_gmt
            existing.youtube_video_id = payload.get("youtube_video_id")
            existing.featured_media_url = payload.get("featured_media_url")
            existing.deleted_at = None  # resurrection: re-published after delete
            existing.last_event_id = event_id
            existing.updated_at = now


async def _mark_post_deleted(
    db: AsyncSession, post_id: int, event_id: int
) -> None:
    """Set the deleted_at tombstone. Idempotent — re-delete is a no-op.

    If the post has never been seen (delete arriving before any publish —
    shouldn't happen but possible with out-of-order delivery), we insert
    a minimal tombstone row so the event log projection stays consistent.
    """
    from models.wordpress_projection import WordPressPost

    now = datetime.now(timezone.utc)

    existing = (
        await db.execute(
            select(WordPressPost).where(WordPressPost.post_id == post_id)
        )
    ).scalar_one_or_none()

    if existing is None:
        # Delete-before-publish — rare but must not fail. Create a minimal
        # tombstone. Backfill will fill in real metadata if the post ever
        # returns to WordPress.
        db.add(
            WordPressPost(
                post_id=post_id,
                post_type="post",
                slug=f"unknown-{post_id}",
                title="(deleted)",
                status="trash",
                permalink="",
                modified_gmt=now,
                youtube_video_id=None,
                featured_media_url=None,
                deleted_at=now,
                last_event_id=event_id,
            )
        )
        return

    if existing.deleted_at is None:
        existing.deleted_at = now
        existing.last_event_id = event_id
        existing.updated_at = now


async def _upsert_terms(
    db: AsyncSession, term_model, slugs: Iterable[str]
) -> None:
    """INSERT any missing term slugs with slug-as-name defaults.

    Idempotent — existing rows are left untouched (their real metadata
    from the backfill / term-webhooks is preserved). We only insert
    rows for slugs we've never seen before, so the FK constraint on the
    association table has something to reference.
    """
    slugs = [s for s in slugs if s]
    if not slugs:
        return

    existing_slugs = set(
        (
            await db.execute(
                select(term_model.slug).where(term_model.slug.in_(slugs))
            )
        )
        .scalars()
        .all()
    )
    missing = [s for s in slugs if s not in existing_slugs]

    for slug in missing:
        db.add(
            term_model(
                slug=slug,
                name=slug,  # Placeholder; reconcile/backfill enriches.
                description=None,
                parent_slug=None,
                wp_term_id=None,
                deleted_at=None,
            )
        )


async def _reconcile_membership(
    db: AsyncSession,
    *,
    assoc_model,
    slug_column: str,
    post_id: int,
    target_slugs: list[str],
) -> None:
    """Make the association table match `target_slugs` for this post_id.

    Set-based reconcile: delete rows for slugs no longer assigned, insert
    rows for slugs newly assigned. Handles adds, removals, and no-ops in
    one pass. Idempotent.
    """
    target_set = {s for s in target_slugs if s}

    existing_rows = (
        await db.execute(
            select(assoc_model).where(assoc_model.post_id == post_id)
        )
    ).scalars().all()
    existing_set = {getattr(row, slug_column) for row in existing_rows}

    to_remove = existing_set - target_set
    to_add = target_set - existing_set

    if to_remove:
        await db.execute(
            delete(assoc_model)
            .where(assoc_model.post_id == post_id)
            .where(getattr(assoc_model, slug_column).in_(to_remove))
        )

    for slug in to_add:
        db.add(assoc_model(**{"post_id": post_id, slug_column: slug}))


# ─────────────────────────────────────────────────────────────────────────────
# Term-event projection (mu-plugin v0.6)
# ─────────────────────────────────────────────────────────────────────────────


# Maps webhook `taxonomy` field to the term model. Kept explicit rather
# than dynamic import so any typo fails at review, not at prod runtime.
_TAXONOMY_MODEL_MAP: dict[str, str] = {
    "series": "WordPressSeries",
    "category": "WordPressCategory",
    "post_tag": "WordPressTag",
}


async def project_term_event(
    db: AsyncSession, payload: dict[str, Any]
) -> None:
    """Project one term-lifecycle webhook event onto Layer 2.

    Payload shape (mu-plugin v0.6):
        {
            "event": "term_updated" | "term_deleted",
            "taxonomy": "series" | "category" | "post_tag",
            "term_id": <int>,
            "slug": <str>,
            "name": <str>,
            "description": <str|null>,
            "parent_slug": <str|null>,
            ...
        }

    - term_updated: UPSERT — inserts if missing, updates metadata if present.
      Detects slug renames via matching wp_term_id + differing slug — for
      the `series` taxonomy this triggers alias handling (WPR-8): the old
      slug goes into wordpress_series_slug_alias, the master row's slug
      updates to the new slug, and M:M memberships move across atomically.
      For category / post_tag, the same rename logic applies but no alias
      table (renames are rare there; add parallel alias table if needed).
    - term_deleted: sets deleted_at tombstone.
    """
    from models import wordpress_projection

    taxonomy = payload["taxonomy"]
    model_name = _TAXONOMY_MODEL_MAP.get(taxonomy)
    if model_name is None:
        raise ValueError(f"unknown taxonomy: {taxonomy!r}")
    term_model = getattr(wordpress_projection, model_name)

    slug = payload["slug"]
    event = payload["event"]
    term_id = payload.get("term_id")
    now = datetime.now(timezone.utc)

    if event == "term_deleted":
        existing = (
            await db.execute(
                select(term_model).where(term_model.slug == slug)
            )
        ).scalar_one_or_none()
        if existing is not None and existing.deleted_at is None:
            existing.deleted_at = now
            existing.last_updated = now
        return

    # term_updated flow — first try slug lookup, then wp_term_id lookup
    # for rename detection.
    existing_by_slug = (
        await db.execute(
            select(term_model).where(term_model.slug == slug)
        )
    ).scalar_one_or_none()

    if existing_by_slug is not None:
        # Same slug we already knew about — plain metadata UPSERT.
        _apply_term_metadata(existing_by_slug, payload, now)
        return

    # Slug not found — check if this is a rename of a known term_id.
    existing_by_term_id = None
    if term_id:
        existing_by_term_id = (
            await db.execute(
                select(term_model).where(term_model.wp_term_id == term_id)
            )
        ).scalar_one_or_none()

    if existing_by_term_id is not None:
        # RENAME: same wp_term_id, new slug. Move the master row + M:M
        # memberships to the new slug, drop an alias for the old slug.
        old_slug = existing_by_term_id.slug
        await _rename_term(
            db,
            term_model=term_model,
            taxonomy=taxonomy,
            old_slug=old_slug,
            new_slug=slug,
            payload=payload,
            now=now,
        )
        return

    # No match by slug or term_id — brand new term. INSERT.
    db.add(
        term_model(
            slug=slug,
            name=payload.get("name") or slug,
            description=payload.get("description"),
            parent_slug=payload.get("parent_slug"),
            wp_term_id=term_id,
            deleted_at=None,
        )
    )


def _apply_term_metadata(existing, payload: dict[str, Any], now: datetime) -> None:
    """Overwrite metadata fields on an existing term row."""
    existing.name = payload.get("name") or existing.name
    existing.description = payload.get("description")
    existing.parent_slug = payload.get("parent_slug")
    if payload.get("term_id") is not None:
        existing.wp_term_id = payload["term_id"]
    existing.deleted_at = None  # resurrection
    existing.last_updated = now


async def _rename_term(
    db: AsyncSession,
    *,
    term_model,
    taxonomy: str,
    old_slug: str,
    new_slug: str,
    payload: dict[str, Any],
    now: datetime,
) -> None:
    """Move a term row + its M:M memberships from old_slug to new_slug.

    Order matters — Postgres FK checks are per-statement, and we need to
    respect the FK from association tables → term.slug. Approach:

      1. UPDATE the master term row to have the new slug + refreshed metadata.
         Association tables have ON UPDATE CASCADE via app-layer intent, but
         Postgres FK enforcement means we have to update the child rows
         either before or in the same statement. Sqlite tests don't enforce
         FKs on UPDATE, so the two paths behave differently — we do the
         child updates explicitly to keep behavior identical.
      2. UPDATE the M:M association rows: replace old_slug with new_slug.
      3. INSERT an alias row (series only) so external links resolve.
    """
    from models.wordpress_projection import (
        WordPressPostCategory,
        WordPressPostSeries,
        WordPressPostTag,
        WordPressSeriesSlugAlias,
    )
    from sqlalchemy import update

    # Slug FK enforcement is done at the term_model + assoc_model level via
    # ON DELETE CASCADE, not ON UPDATE CASCADE. So we must manually update
    # the child rows first (or in the same tx before commit). Postgres
    # will error if we UPDATE the parent first while children still
    # reference the old slug — so children first.
    assoc_model = None
    slug_column: str | None = None
    if taxonomy == "series":
        assoc_model, slug_column = WordPressPostSeries, "series_slug"
    elif taxonomy == "category":
        assoc_model, slug_column = WordPressPostCategory, "category_slug"
    elif taxonomy == "post_tag":
        assoc_model, slug_column = WordPressPostTag, "tag_slug"

    if assoc_model is not None:
        # Bulk UPDATE the M:M rows.
        col = getattr(assoc_model, slug_column)
        await db.execute(
            update(assoc_model).where(col == old_slug).values({slug_column: new_slug})
        )

    # UPDATE the master term row.
    await db.execute(
        update(term_model)
        .where(term_model.slug == old_slug)
        .values(
            slug=new_slug,
            name=payload.get("name") or new_slug,
            description=payload.get("description"),
            parent_slug=payload.get("parent_slug"),
            wp_term_id=payload.get("term_id"),
            deleted_at=None,
            last_updated=now,
        )
    )

    # Record the rename in the alias table (series only for now — WPR-8 scope).
    if taxonomy == "series":
        # Idempotency: if we've already recorded this exact alias, skip.
        existing_alias = (
            await db.execute(
                select(WordPressSeriesSlugAlias).where(
                    WordPressSeriesSlugAlias.old_slug == old_slug
                )
            )
        ).scalar_one_or_none()
        if existing_alias is None:
            db.add(
                WordPressSeriesSlugAlias(
                    old_slug=old_slug,
                    current_slug=new_slug,
                    renamed_at=now,
                )
            )
        else:
            # Chained rename: A → B, then B → C. Update the alias so old
            # `A` points to C (current), keeping single-hop lookups.
            existing_alias.current_slug = new_slug
            existing_alias.renamed_at = now

        # Also update ANY existing aliases whose current_slug == old_slug —
        # they need to point at new_slug now (transitive fix).
        await db.execute(
            update(WordPressSeriesSlugAlias)
            .where(WordPressSeriesSlugAlias.current_slug == old_slug)
            .values(current_slug=new_slug, renamed_at=now)
        )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _parse_modified_gmt(value: Any) -> datetime:
    """Same parser as handler._parse_modified_gmt — WordPress format tolerant."""
    if isinstance(value, datetime):
        return _ensure_utc(value)
    if not isinstance(value, str):
        raise ValueError(f"modified_gmt must be str, got {type(value).__name__}")
    normalized = value.replace(" ", "T", 1)
    parsed = datetime.fromisoformat(normalized)
    return _ensure_utc(parsed)


def _ensure_utc(value: datetime) -> datetime:
    """Coerce a datetime to tz-aware UTC. Naive datetimes assumed UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
