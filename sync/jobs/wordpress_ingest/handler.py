"""wordpress_ingest — SQS-triggered Lambda handler.

Drains the `contenthub-{env}-wordpress-ingest-queue` SQS queue populated
by the ECS webhook route (`backend/src/wordpress/router.py`). For each
message: parse the WordPress event payload, insert into
`wordpress_events` (idempotent on `(post_id, modified_gmt)`), and ack.

Event source: SQS event source mapping — batches of 1 for backpressure
control on DB writes.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from shared.cht_cache import clear_cht_catalog_cache
from shared.runtime import configure_logging, install_paths, run_async


def _parse_modified_gmt(value: Any) -> datetime:
    """WordPress emits `2026-07-09 21:00:00` (space-separated, no TZ). Treat as UTC."""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError(f"modified_gmt must be str, got {type(value).__name__}")
    # Accept both space and 'T' separators — the mu-plugin uses space
    # (matching WordPress's stored `post_modified_gmt` format).
    normalized = value.replace(" ", "T", 1)
    return datetime.fromisoformat(normalized)


_POST_EVENTS = frozenset({"published", "updated", "deleted"})
_TERM_EVENTS = frozenset({"term_updated", "term_deleted"})


async def _insert_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Insert one WordPress webhook event, then project to Layer 2.

    Post events (published / updated / deleted) go through the wordpress_events
    append-only log AND the Layer 2 projection tables in the same transaction.
    If the projection fails, the transaction rolls back and SQS redelivers —
    the event log stays consistent with projected state.

    Term events (term_updated / term_deleted, from mu-plugin v0.6) skip the
    Layer 1 event log — there is no per-webhook history for term-lifecycle
    events; only the current-state projection matters. The event log's
    (post_id, modified_gmt) uniqueness key isn't meaningful for term events
    either.

    Idempotency:
      - Post events: idempotent on (post_id, modified_gmt) at Layer 1.
        Projection uses SELECT+branch UPSERT, also idempotent.
      - Term events: idempotent via SELECT+branch UPSERT at Layer 2.
    """
    from database import async_session_maker

    event = payload.get("event")

    if event in _TERM_EVENTS:
        return await _insert_term_event(payload)

    if event not in _POST_EVENTS:
        # Should have been rejected at the router — defensive.
        return {"status": "error", "reason": f"unknown event: {event!r}"}

    from jobs.wordpress_ingest_projection import project_post_event
    from models.wordpress_event import WordPressEvent
    from sqlalchemy import select

    modified_gmt = _parse_modified_gmt(payload["modified_gmt"])
    post_id = int(payload["post_id"])

    async with async_session_maker() as db:
        # Idempotency check — if we've already seen this exact event, skip.
        existing = (
            await db.execute(
                select(WordPressEvent.id)
                .where(WordPressEvent.post_id == post_id)
                .where(WordPressEvent.modified_gmt == modified_gmt)
            )
        ).scalar_one_or_none()

        if existing is not None:
            return {
                "status": "duplicate",
                "post_id": post_id,
                "modified_gmt": payload["modified_gmt"],
                "existing_id": existing,
            }

        row = WordPressEvent(
            post_id=post_id,
            modified_gmt=modified_gmt,
            event=payload["event"],
            post_type=payload["post_type"],
            slug=payload["slug"],
            title=payload["title"],
            status=payload["status"],
            permalink=payload["permalink"],
            categories=payload["categories"],
            tags=payload["tags"],
            # `series` added in mu-plugin v0.5. Tolerant of pre-v0.5
            # payloads that omit the field — column defaults to [] server
            # side but SQLAlchemy needs an explicit value to avoid a NULL
            # constraint violation on this INSERT path.
            series=payload.get("series") or [],
            site_url=payload["site_url"],
            acf=payload.get("acf"),
            raw_payload=payload,
            signature_verified=True,  # ECS route already validated
            youtube_video_id=payload.get("youtube_video_id"),
            featured_media_url=payload.get("featured_media_url"),
        )
        db.add(row)
        # Flush to get row.id populated (required as last_event_id in
        # wordpress_posts) without committing — projection runs in the
        # same transaction so a failure downstream rolls back everything.
        await db.flush()
        inserted_id = row.id

        # Layer 2 projection — inside the same transaction.
        await project_post_event(db, payload, inserted_id)

        await db.commit()

    return {
        "status": "inserted",
        "id": inserted_id,
        "post_id": post_id,
        "event": payload["event"],
    }


async def _insert_term_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Handle term-lifecycle webhook events (mu-plugin v0.6).

    Layer 1 skipped — the event log's uniqueness key isn't meaningful for
    terms, and full term history isn't a requirement (backfill can rebuild
    from WP REST at any time).
    """
    from database import async_session_maker
    from jobs.wordpress_ingest_projection import project_term_event

    async with async_session_maker() as db:
        await project_term_event(db, payload)
        await db.commit()

    return {
        "status": "term_projected",
        "event": payload["event"],
        "taxonomy": payload.get("taxonomy"),
        "slug": payload.get("slug"),
    }


async def _process_record(record: dict[str, Any]) -> dict[str, Any]:
    """One SQS record → one wordpress_events row."""
    body = record.get("body", "{}")
    try:
        payload = json.loads(body) if isinstance(body, str) else body
    except json.JSONDecodeError as exc:
        return {"status": "error", "reason": f"malformed json: {exc}"}

    if not isinstance(payload, dict):
        return {"status": "error", "reason": "payload not a JSON object"}

    return await _insert_event(payload)


async def _run(event: dict) -> dict:
    records = event.get("Records", [])
    if not records:
        # Manual invocation with a bare payload — treat as a single event.
        payload = event if isinstance(event, dict) else {}
        if payload:
            result = await _insert_event(payload)
            _clear_cht_cache_if_material([result])
            return {"status": "ok", "job": "wordpress_ingest", "results": [result]}
        return {"status": "ok", "job": "wordpress_ingest", "results": []}

    results = []
    for record in records:
        try:
            result = await _process_record(record)
        except Exception as exc:
            # Any unhandled error — let SQS retry (message stays in queue).
            # After max_receive_count (3), SQS routes to DLQ.
            raise
        results.append(result)

    _clear_cht_cache_if_material(results)

    return {"status": "ok", "job": "wordpress_ingest", "results": results}


def _clear_cht_cache_if_material(results: list[dict[str, Any]]) -> None:
    """Invalidate CHT's catalog cache after a WP event lands.

    Skip when nothing material happened (all duplicates or errors) —
    duplicates mean CHT already reflects this state, so a cache-clear
    would just churn the CDN with no benefit.

    Non-blocking: `clear_cht_catalog_cache` catches its own exceptions
    and logs a warning. A cache-clear failure MUST NOT fail the Lambda
    invocation — the WP event is already durably in the DB, and the
    5-min TTL will catch up eventually.
    """
    material_statuses = {"inserted", "term_projected"}
    material = any(r.get("status") in material_statuses for r in results)
    if not material:
        return
    clear_cht_catalog_cache(job="wordpress_ingest")


def handler(event: dict, context) -> dict:
    install_paths()
    configure_logging()
    return run_async(_run(event or {}))
