"""wordpress_backfill — one-shot Lambda that populates youtube_video_id +
featured_media_url on existing wordpress_events rows.

Runs against a WordPress site that ingested events BEFORE the mu-plugin v0.2
(which extracts these fields on the WP side). Fetches each unique post_id
via the WordPress REST API and updates the row.

Design:
- **Idempotent**: only UPDATEs rows where `youtube_video_id IS NULL AND event != 'deleted'`.
  Re-invocations after a full run are no-ops.
- **Rate limited**: sleeps 250ms between REST hits to avoid tripping WAF.
- **Fault tolerant**: individual post fetch failures are logged and skipped;
  the run continues. Returns per-row status.
- **No new secrets**: WP REST is publicly readable for published posts.

Invocation:
    aws lambda invoke \\
      --function-name contenthub-dev-sync-wordpress-backfill \\
      --payload '{}' \\
      /tmp/resp.json && cat /tmp/resp.json

Payload (all optional):
    {
      "wp_base_url": "https://communityhealth.media",  # defaults to WP_BASE_URL env
      "batch_size": 500,                                # cap rows processed this invoke
      "dry_run": false                                  # if true, no UPDATE, just report
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

from shared.runtime import configure_logging, install_paths, run_async

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
    """Read WordPress app-password credentials from Secrets Manager.

    Returns (user, app_password) or (None, None) if not configured.
    WordPress REST WAF rejects unauthenticated requests to
    /wp-json/wp/v2/posts/*; an application password bypasses that
    while being revokable independently from a login password.
    """
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
    """Fetch one WordPress post via REST.

    Returns (data, status) where status is one of:
      - 'ok': valid post payload in data
      - 'not_found': WP returned 404 (post deleted or fake/seed ID)
      - 'rate_limited': WP returned 429 (caller should back off)
      - 'error': other HTTP or network error
    """
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


async def _fetch_featured_media_url(
    client: httpx.AsyncClient, base_url: str, post_id: int
) -> str | None:
    """Some WP configs don't expose featured_media_url on the post object.
    Fall back to /media/<id> when featured_media (an ID) is populated."""
    url = f"{base_url.rstrip('/')}/wp-json/wp/v2/media/{post_id}"
    params = {"_fields": "source_url"}
    try:
        resp = await client.get(url, params=params)
        if resp.status_code != 200:
            return None
        return resp.json().get("source_url")
    except httpx.HTTPError:
        return None


async def _process_post(
    client: httpx.AsyncClient,
    base_url: str,
    post_id: int,
) -> dict[str, Any]:
    """Fetch WP data + return status + extracted fields.

    Statuses:
      - 'ok': fetched successfully; youtube_video_id may still be None if the
        post has no YouTube embed
      - 'not_found': WP returned 404 (seed IDs, deleted posts)
      - 'rate_limited': WP returned 429; caller must back off
      - 'error': other HTTP/network failure
    """
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


async def _run(event: dict[str, Any]) -> dict[str, Any]:
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
        "wordpress_backfill start",
        extra={
            "post_count": len(post_ids),
            "wp_base_url": wp_base_url,
            "dry_run": dry_run,
        },
    )

    if not post_ids:
        return {
            "status": "ok",
            "job": "wordpress_backfill",
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
    would_update = 0  # dry-run only; how many rows would have been written
    skipped_not_found = 0
    skipped_no_data = 0
    rate_limited = 0
    failures = 0
    results_summary: list[dict[str, Any]] = []

    headers = {"User-Agent": _UA}
    wp_user, wp_app_pw = _load_wp_credentials()
    auth = (wp_user, wp_app_pw) if wp_user and wp_app_pw else None
    log.info(
        "wordpress_backfill auth",
        extra={"authenticated": auth is not None, "wp_user": wp_user or "none"},
    )
    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT_S, headers=headers, follow_redirects=True, auth=auth
    ) as client:
        for post_id in post_ids:
            info = await _process_post(client, wp_base_url, post_id)

            if info["status"] == "rate_limited":
                # Row stays eligible for future runs. Back off and STOP the
                # batch — hitting 429s means we're too fast; better to end
                # early and let another invocation resume than keep firing.
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
                # Update all rows for this post_id (there may be publish + updates)
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

    processed = len(results_summary)  # actual attempts, may be < len(post_ids) if halted
    log.info(
        "wordpress_backfill done",
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

    # Clear CHT cache only when real writes happened
    if updated > 0 and not dry_run:
        from shared.cht_cache import clear_cht_catalog_cache

        clear_cht_catalog_cache(job="wordpress_backfill")

    return {
        "status": "ok",
        "job": "wordpress_backfill",
        "dry_run": dry_run,
        "post_ids_queued": len(post_ids),
        "processed": processed,
        "updated": updated,
        "would_update_dry_run": would_update,
        "skipped_not_found": skipped_not_found,
        "skipped_no_data": skipped_no_data,
        "rate_limited": rate_limited,
        "failures": failures,
        # Sample of first 10 results for CloudWatch visibility
        "sample": results_summary[:10],
    }


def handler(event: dict, context) -> dict:
    install_paths()
    configure_logging()
    return run_async(_run(event or {}))
