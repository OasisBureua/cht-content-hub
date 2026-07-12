"""wordpress_seed — one-shot Lambda that ingests ALL published WordPress
posts from communityhealth.media into wordpress_events.

Different from wordpress_backfill (which only updates youtube_video_id
on rows that already exist): this seeds the whole editorial catalog
into the table so /clips filters reflect the true WordPress state.

Design:
- Pages through /wp-json/wp/v2/posts?per_page=100&page=N (WP REST max)
- Resolves category + tag numeric IDs → slugs (fetches vocab once at start)
- Extracts youtube_video_id from post content HTML (same regex as mu-plugin)
- INSERT ... ON CONFLICT DO NOTHING on UNIQUE (post_id, modified_gmt)
- Fully idempotent — re-invocations skip rows that already match

Auth: WordPress Application Password from Secrets Manager
      (wordpress_admin_user + wordpress_admin_app_password keys on
      contenthub-dev-app-secrets).

Rate limited: 1 req/sec cadence (same as wordpress_backfill). WP's WAF
throttles above ~4 req/sec.

Invocation:
    aws lambda invoke \\
      --function-name contenthub-dev-sync-wordpress-seed \\
      --payload '{}' \\
      /tmp/resp.json && cat /tmp/resp.json

Payload (all optional):
    {
      "wp_base_url": "https://communityhealth.media",  # defaults
      "max_pages": 10,   # cap pages to fetch this invoke
      "dry_run": false   # if true, no INSERT, just report
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
_PER_PAGE = 100  # WP REST maximum
_REQUEST_DELAY_S = 1.0
_HTTP_TIMEOUT_S = 20.0
_RATE_LIMIT_BACKOFF_S = 30.0


def _extract_youtube_id(content: str | None) -> str | None:
    if not content:
        return None
    match = _YOUTUBE_ID_PATTERN.search(content)
    return match.group(1) if match else None


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
    return (
        payload.get("wordpress_admin_user") or None,
        payload.get("wordpress_admin_app_password") or None,
    )


async def _fetch_vocab(
    client: httpx.AsyncClient, base_url: str, kind: str
) -> dict[int, str]:
    """Fetch /categories or /tags — returns {id: slug}. Handles multi-page."""
    result: dict[int, str] = {}
    page = 1
    while True:
        url = f"{base_url.rstrip('/')}/wp-json/wp/v2/{kind}"
        resp = await client.get(
            url, params={"per_page": _PER_PAGE, "page": page, "_fields": "id,slug"}
        )
        if resp.status_code == 400 and page > 1:
            break  # ran off end
        resp.raise_for_status()
        items = resp.json()
        if not items:
            break
        for item in items:
            result[int(item["id"])] = item["slug"]
        if len(items) < _PER_PAGE:
            break
        page += 1
        await asyncio.sleep(_REQUEST_DELAY_S)
    return result


def _parse_modified_gmt(value: str | None) -> str | None:
    """WP returns ISO-8601 without timezone. Normalize to include Z for storage."""
    if not value:
        return None
    if value.endswith("Z") or "+" in value or "-" in value[10:]:
        return value
    return value + "Z"


async def _fetch_posts_page(
    client: httpx.AsyncClient, base_url: str, page: int
) -> tuple[list[dict[str, Any]], str]:
    """Fetch one page of posts. Returns (posts, status).

    Statuses: 'ok', 'empty' (no more pages), 'rate_limited', 'error'.
    """
    url = f"{base_url.rstrip('/')}/wp-json/wp/v2/posts"
    params = {
        "per_page": _PER_PAGE,
        "page": page,
        "status": "publish",
        "_fields": (
            "id,slug,link,type,status,modified_gmt,date_gmt,title,"
            "categories,tags,content,featured_media_url,"
            "jetpack_featured_media_url"
        ),
    }
    try:
        resp = await client.get(url, params=params)
        if resp.status_code == 400:
            # Past the last page
            return [], "empty"
        if resp.status_code == 429:
            log.warning(
                "wp rate limited",
                extra={"page": page, "retry_after": resp.headers.get("retry-after")},
            )
            return [], "rate_limited"
        resp.raise_for_status()
        return resp.json(), "ok"
    except httpx.HTTPError as exc:
        log.warning("wp page fetch failed", extra={"page": page, "error": str(exc)})
        return [], "error"


async def _insert_post(
    db, sql_text, post: dict[str, Any], categories: dict[int, str], tags: dict[int, str]
) -> str:
    """Idempotent INSERT into wordpress_events. Returns 'inserted' or 'skipped'."""
    post_id = int(post["id"])
    modified_gmt = _parse_modified_gmt(post.get("modified_gmt"))
    if not modified_gmt:
        modified_gmt = _parse_modified_gmt(post.get("date_gmt"))
    if not modified_gmt:
        return "skipped"

    slug = post.get("slug") or ""
    permalink = post.get("link") or ""
    post_type = post.get("type") or "post"
    status = post.get("status") or "publish"
    title = (post.get("title") or {}).get("rendered", "")
    content_html = (post.get("content") or {}).get("rendered", "")

    cat_ids = post.get("categories") or []
    tag_ids = post.get("tags") or []
    cat_slugs = [categories[i] for i in cat_ids if i in categories]
    tag_slugs = [tags[i] for i in tag_ids if i in tags]

    yt_id = _extract_youtube_id(content_html)
    fm_url = post.get("featured_media_url") or post.get("jetpack_featured_media_url")

    raw_payload = {
        "event": "seed",
        "post_id": post_id,
        "post_type": post_type,
        "slug": slug,
        "title": title,
        "status": status,
        "modified_gmt": modified_gmt,
        "permalink": permalink,
        "categories": cat_slugs,
        "tags": tag_slugs,
        "site_url": "https://communityhealth.media",
        "youtube_video_id": yt_id,
        "featured_media_url": fm_url,
        "source": "wordpress_seed",
    }

    # INSERT ... ON CONFLICT DO NOTHING (Postgres). Unique constraint on
    # (post_id, modified_gmt) ensures idempotency: re-runs are no-ops for
    # rows that already exist.
    result = await db.execute(
        sql_text(
            """
            INSERT INTO wordpress_events (
                post_id, modified_gmt, event, post_type, slug, title, status,
                permalink, categories, tags, site_url, acf, raw_payload,
                signature_verified, youtube_video_id, featured_media_url
            ) VALUES (
                :post_id, :modified_gmt, 'seed', :post_type, :slug, :title, :status,
                :permalink,
                CAST(:categories AS jsonb),
                CAST(:tags AS jsonb),
                'https://communityhealth.media',
                NULL,
                CAST(:raw_payload AS jsonb),
                true,
                :youtube_video_id,
                :featured_media_url
            )
            ON CONFLICT (post_id, modified_gmt) DO NOTHING
            """
        ),
        {
            "post_id": post_id,
            "modified_gmt": modified_gmt,
            "post_type": post_type,
            "slug": slug,
            "title": title,
            "status": status,
            "permalink": permalink,
            "categories": json.dumps(cat_slugs),
            "tags": json.dumps(tag_slugs),
            "raw_payload": json.dumps(raw_payload),
            "youtube_video_id": yt_id,
            "featured_media_url": fm_url,
        },
    )
    # rowcount == 1 on insert, 0 on conflict
    inserted = getattr(result, "rowcount", 0) == 1
    return "inserted" if inserted else "skipped"


async def _run(event: dict[str, Any]) -> dict[str, Any]:
    from database import async_session_maker
    from sqlalchemy import text as sql_text

    wp_base_url = event.get("wp_base_url") or os.environ.get(
        "WP_BASE_URL", _DEFAULT_WP_BASE_URL
    )
    max_pages = int(event.get("max_pages") or 20)
    dry_run = bool(event.get("dry_run", False))

    wp_user, wp_app_pw = _load_wp_credentials()
    auth = (wp_user, wp_app_pw) if wp_user and wp_app_pw else None

    log.info(
        "wordpress_seed start",
        extra={
            "wp_base_url": wp_base_url,
            "max_pages": max_pages,
            "dry_run": dry_run,
            "authenticated": auth is not None,
        },
    )

    headers = {"User-Agent": _UA}
    total_seen = 0
    inserted = 0
    skipped = 0
    rate_limited = False
    errors = 0

    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT_S, headers=headers, follow_redirects=True, auth=auth
    ) as client:
        log.info("fetching category + tag vocab")
        categories = await _fetch_vocab(client, wp_base_url, "categories")
        tags = await _fetch_vocab(client, wp_base_url, "tags")
        log.info(
            "vocab loaded",
            extra={"categories": len(categories), "tags": len(tags)},
        )

        for page in range(1, max_pages + 1):
            posts, status = await _fetch_posts_page(client, wp_base_url, page)
            if status == "empty":
                log.info("past last page", extra={"page": page})
                break
            if status == "rate_limited":
                rate_limited = True
                log.warning("halting on rate limit", extra={"page": page})
                await asyncio.sleep(_RATE_LIMIT_BACKOFF_S)
                break
            if status != "ok":
                errors += 1
                await asyncio.sleep(_REQUEST_DELAY_S)
                continue

            total_seen += len(posts)
            log.info(
                "page fetched",
                extra={"page": page, "post_count": len(posts)},
            )

            if not dry_run:
                async with async_session_maker() as db:
                    for post in posts:
                        try:
                            result = await _insert_post(
                                db, sql_text, post, categories, tags
                            )
                            if result == "inserted":
                                inserted += 1
                            else:
                                skipped += 1
                        except Exception as exc:
                            errors += 1
                            log.warning(
                                "insert failed",
                                extra={
                                    "post_id": post.get("id"),
                                    "error": str(exc),
                                },
                            )
                    await db.commit()

            await asyncio.sleep(_REQUEST_DELAY_S)

    log.info(
        "wordpress_seed done",
        extra={
            "total_seen": total_seen,
            "inserted": inserted,
            "skipped_conflict": skipped,
            "errors": errors,
            "rate_limited": rate_limited,
            "dry_run": dry_run,
        },
    )

    if inserted > 0 and not dry_run:
        from shared.cht_cache import clear_cht_catalog_cache

        clear_cht_catalog_cache(job="wordpress_seed")

    return {
        "status": "ok",
        "job": "wordpress_seed",
        "dry_run": dry_run,
        "total_seen": total_seen,
        "inserted": inserted,
        "skipped_conflict": skipped,
        "errors": errors,
        "rate_limited": rate_limited,
    }


def handler(event: dict, context) -> dict:
    install_paths()
    configure_logging()
    return run_async(_run(event or {}))
