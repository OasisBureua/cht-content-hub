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


async def _insert_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Insert one WordPress event into the DB. Idempotent on (post_id, modified_gmt)."""
    from database import async_session_maker
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
            site_url=payload["site_url"],
            acf=payload.get("acf"),
            raw_payload=payload,
            signature_verified=True,  # ECS route already validated
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        inserted_id = row.id

    return {
        "status": "inserted",
        "id": inserted_id,
        "post_id": post_id,
        "event": payload["event"],
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

    return {"status": "ok", "job": "wordpress_ingest", "results": results}


def handler(event: dict, context) -> dict:
    install_paths()
    configure_logging()
    return run_async(_run(event or {}))
