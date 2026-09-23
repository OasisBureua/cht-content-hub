"""backfill_events — one of the ops under wordpress_projection_ops.

Populates youtube_video_id + featured_media_url on existing wordpress_events
rows that predate mu-plugin v0.2 (which extracts those fields on the WP
side at ingest time).

Runs the same code path the old standalone `wordpress_backfill` Lambda
did — moved here as part of the consolidation into one wordpress-domain
Lambda.

Design:
- Idempotent: only UPDATEs rows where youtube_video_id IS NULL AND event != 'deleted'.
- Rate limited (1 req/sec + 30s back-off on 429).
- Fault tolerant: individual post fetch failures skip the row and continue.

Payload:
    {
      "op": "backfill_events",
      "wp_base_url": "https://communityhealth.media",
      "batch_size": 500,
      "dry_run": false
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

import boto3
import httpx

log = logging.getLogger(__name__)

_YOUTUBE_ID_PATTERN = re.compile(
    r"(?:youtube\.com/(?:embed/|watch\?v=|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)

_DEFAULT_WP_BASE_URL = "https://communityhealth.media"
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_REQUEST_DELAY_S = 1.0
_HTTP_TIMEOUT_S = 15.0
_RATE_LIMIT_BACKOFF_S = 30.0


def _load_wp_credentials() -> tuple[str | None, str | None]:
    arn = os.environ.get("APP_SECRETS_ARN", "")
    if not arn:
        return None, None
    try:
        client = boto3.client(
            "secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1")
        )
        payload = json.loads(client.get_secret_value(SecretId=arn)["SecretString"])
    except Exception as exc:
        log.warning("could not load app secrets", extra={"error": str(exc)})
        return None, None
    user = payload.get("wordpress_admin_user") or None
    app_pw = payload.get("wordpress_admin_app_password") or None
    return user, app_pw


def _extract_youtube_id(content: str | None) -> str | None:
    if not content:
        return None
    match = _YOUTUBE_ID_PATTERN.search(content)
    return match.group(1) if match else None


async def _fetch_wp_post(
    client: httpx.AsyncClient, base_url: str, post_id: int
) -> tuple[dict[str, Any] | None, str]:
    """Fetch one WordPress post via REST. Returns (data, status)."""
    url = f"{base_url.rstrip('/')}/wp-json/wp/v2/posts/{post_id}"
    params = {"_fields": "id,content,featured_media_url,jetpack_featured_media_url"}
    try:
        resp = await client.get(url, params=params)
        if resp.status_code == 404:
            log.info("wp post not found", extra={"post_id": post_id})
            return None, "not_found"
        if resp.status_code == 429:
            log.warning(
                "wp rate limited",
                extra={
                    "post_id": post_id,
                    "retry_after": resp.headers.get("retry-after"),
                },
            )
            return None, "rate_limited"
        resp.raise_for_status()
        return resp.json(), "ok"
    except httpx.HTTPError as exc:
        log.warning(
            "wp post fetch failed",
            extra={"post_id": post_id, "error": str(exc)},
        )
        return None, "error"


async def _process_post(
    client: httpx.AsyncClient,
    base_url: str,
    post_id: int,
) -> dict[str, Any]:
    data, status = await _fetch_wp_post(client, base_url, post_id)
    if status != "ok" or data is None:
        return {
            "post_id": post_id,
            "status": status,
            "youtube_video_id": None,
            "featured_media_url": None,
        }
    content_html = (data.get("content") or {}).get("rendered", "")
    yt_id = _extract_youtube_id(content_html)
    fm_url = (
        data.get("featured_media_url")
        or data.get("jetpack_featured_media_url")
        or None
    )
    return {
        "post_id": post_id,
        "status": "ok",
        "youtube_video_id": yt_id,
        "featured_media_url": fm_url,
    }


async def run(event: dict[str, Any]) -> dict[str, Any]:
    from database import async_session_maker
    from sqlalchemy import text as sql_text

    wp_base_url = event.get("wp_base_url") or os.environ.get(
        "WP_BASE_URL", _DEFAULT_WP_BASE_URL
    )
    batch_size = int(event.get("batch_size") or 500)
    dry_run = bool(event.get("dry_run", False))

    async with async_session_maker() as db:
        rows = list(
            (
                await db.execute(
                    sql_text(
                        """
                        SELECT DISTINCT post_id
                        FROM wordpress_events
                        WHERE youtube_video_id IS NULL
                          AND event != 'deleted'
                        ORDER BY post_id
                        LIMIT :limit
                        """
                    ),
                    {"limit": batch_size},
                )
            ).mappings()
        )
        post_ids = [int(r["post_id"]) for r in rows]

    log.info(
        "backfill_events start",
        extra={
            "post_count": len(post_ids),
            "wp_base_url": wp_base_url,
            "dry_run": dry_run,
        },
    )

    if not post_ids:
        return {
            "status": "ok",
            "op": "backfill_events",
            "dry_run": dry_run,
            "post_ids_queued": 0,
            "processed": 0,
            "updated": 0,
            "would_update_dry_run": 0,
            "skipped_not_found": 0,
            "skipped_no_data": 0,
            "rate_limited": 0,
            "failures": 0,
        }

    updated = 0
    would_update = 0
    skipped_not_found = 0
    skipped_no_data = 0
    rate_limited = 0
    failures = 0
    results_summary: list[dict[str, Any]] = []

    headers = {"User-Agent": _UA}
    wp_user, wp_app_pw = _load_wp_credentials()
    auth = (wp_user, wp_app_pw) if wp_user and wp_app_pw else None
    log.info(
        "backfill_events auth",
        extra={"authenticated": auth is not None, "wp_user": wp_user or "none"},
    )
    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT_S, headers=headers, follow_redirects=True, auth=auth
    ) as client:
        for post_id in post_ids:
            info = await _process_post(client, wp_base_url, post_id)

            if info["status"] == "rate_limited":
                rate_limited += 1
                results_summary.append(info)
                log.warning(
                    "backfill halting on rate limit",
                    extra={
                        "post_id": post_id,
                        "processed_so_far": len(results_summary),
                    },
                )
                await asyncio.sleep(_RATE_LIMIT_BACKOFF_S)
                break

            if info["status"] == "not_found":
                skipped_not_found += 1
                results_summary.append(info)
                await asyncio.sleep(_REQUEST_DELAY_S)
                continue

            if info["status"] != "ok":
                failures += 1
                results_summary.append(info)
                await asyncio.sleep(_REQUEST_DELAY_S)
                continue

            yt_id = info["youtube_video_id"]
            fm_url = info["featured_media_url"]

            if not yt_id and not fm_url:
                skipped_no_data += 1
                results_summary.append({**info, "status": "no_data"})
                await asyncio.sleep(_REQUEST_DELAY_S)
                continue

            if dry_run:
                would_update += 1
                results_summary.append({**info, "status": "dry_run"})
                await asyncio.sleep(_REQUEST_DELAY_S)
                continue

            async with async_session_maker() as db:
                await db.execute(
                    sql_text(
                        """
                        UPDATE wordpress_events
                        SET youtube_video_id = COALESCE(youtube_video_id, :yt_id),
                            featured_media_url = COALESCE(featured_media_url, :fm_url)
                        WHERE post_id = :post_id
                          AND event != 'deleted'
                        """
                    ),
                    {
                        "yt_id": yt_id,
                        "fm_url": fm_url,
                        "post_id": post_id,
                    },
                )
                await db.commit()

            updated += 1
            results_summary.append(info)
            await asyncio.sleep(_REQUEST_DELAY_S)

    processed = len(results_summary)
    log.info(
        "backfill_events done",
        extra={
            "post_ids_queued": len(post_ids),
            "processed": processed,
            "updated": updated,
            "would_update_dry_run": would_update,
            "skipped_not_found": skipped_not_found,
            "skipped_no_data": skipped_no_data,
            "rate_limited": rate_limited,
            "failures": failures,
            "dry_run": dry_run,
        },
    )

    if updated > 0 and not dry_run:
        from shared.cht_cache import clear_cht_catalog_cache

        clear_cht_catalog_cache(job="wordpress_projection_ops.backfill_events")

    return {
        "status": "ok",
        "op": "backfill_events",
        "dry_run": dry_run,
        "post_ids_queued": len(post_ids),
        "processed": processed,
        "updated": updated,
        "would_update_dry_run": would_update,
        "skipped_not_found": skipped_not_found,
        "skipped_no_data": skipped_no_data,
        "rate_limited": rate_limited,
        "failures": failures,
        "sample": results_summary[:10],
    }
