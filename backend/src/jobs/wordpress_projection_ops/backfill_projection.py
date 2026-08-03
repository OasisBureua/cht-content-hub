"""backfill_projection — one of the ops under wordpress_projection_ops.

Hydrates Layer 2 (wordpress_posts, wordpress_series/_categories/_tags,
M:M association tables) from WordPress REST. Fetches term inventories
first (name/description/parent/term_id), then post membership arrays,
feeds both through the shared projection module.

Idempotent by construction (UPSERT + set-based M:M reconcile).

Payload:
    {
      "op": "backfill_projection",
      "wp_base_url": "https://communityhealth.media",
      "max_pages": 20,
      "taxonomies": ["series", "category", "post_tag"],
      "dry_run": false
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import boto3
import httpx

log = logging.getLogger(__name__)

_DEFAULT_WP_BASE_URL = "https://communityhealth.media"
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_PER_PAGE = 100
_REQUEST_DELAY_S = 1.0
_HTTP_TIMEOUT_S = 20.0

_TAXONOMY_REST_PATH: dict[str, str] = {
    "series": "series",
    "category": "categories",
    "post_tag": "tags",
}

_POST_TAXONOMY_ID_KEY: dict[str, str] = {
    "series": "series",
    "category": "categories",
    "post_tag": "tags",
}


def _load_wp_credentials() -> tuple[str | None, str | None]:
    arn = os.environ.get("APP_SECRETS_ARN", "")
    if not arn:
        return None, None
    try:
        client = boto3.client(
            "secretsmanager",
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )
        payload = json.loads(client.get_secret_value(SecretId=arn)["SecretString"])
    except Exception as exc:
        log.warning("could not load app secrets", extra={"error": str(exc)})
        return None, None
    return (
        payload.get("wordpress_admin_user") or None,
        payload.get("wordpress_admin_app_password") or None,
    )


def _parse_modified_gmt(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = value[:-1] if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def _fetch_terms(
    client: httpx.AsyncClient, base_url: str, rest_path: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    page = 1
    while True:
        url = f"{base_url.rstrip('/')}/wp-json/wp/v2/{rest_path}"
        try:
            resp = await client.get(
                url,
                params={
                    "per_page": _PER_PAGE,
                    "page": page,
                    "_fields": "id,slug,name,description,parent",
                },
            )
        except httpx.HTTPError as exc:
            log.warning(
                "term page fetch failed",
                extra={"rest_path": rest_path, "page": page, "error": str(exc)},
            )
            break
        if resp.status_code == 400 and page > 1:
            break
        if resp.status_code >= 400:
            log.warning(
                "term fetch non-2xx",
                extra={
                    "rest_path": rest_path,
                    "page": page,
                    "status": resp.status_code,
                },
            )
            break
        items = resp.json()
        if not items:
            break
        out.extend(items)
        if len(items) < _PER_PAGE:
            break
        page += 1
        await asyncio.sleep(_REQUEST_DELAY_S)
    return out


async def _fetch_posts_page(
    client: httpx.AsyncClient, base_url: str, page: int
) -> tuple[list[dict[str, Any]], str]:
    url = f"{base_url.rstrip('/')}/wp-json/wp/v2/posts"
    params = {
        "per_page": _PER_PAGE,
        "page": page,
        "status": "publish",
        "_fields": (
            "id,slug,link,type,status,modified_gmt,date_gmt,title,"
            "categories,tags,series,content,featured_media_url,"
            "jetpack_featured_media_url"
        ),
    }
    try:
        resp = await client.get(url, params=params)
        if resp.status_code == 400:
            return [], "empty"
        if resp.status_code == 429:
            return [], "rate_limited"
        resp.raise_for_status()
        return resp.json(), "ok"
    except httpx.HTTPError as exc:
        log.warning("posts page fetch failed", extra={"page": page, "error": str(exc)})
        return [], "error"


async def _project_terms_for_taxonomy(
    db, taxonomy: str, terms: list[dict[str, Any]]
) -> tuple[dict[int, str], int]:
    from jobs.wordpress_ingest_projection import project_term_event

    id_to_slug: dict[int, str] = {}
    projected = 0

    id_lookup = {int(t["id"]): t["slug"] for t in terms}

    for term in terms:
        term_id = int(term["id"])
        slug = term["slug"]
        id_to_slug[term_id] = slug

        parent_id = term.get("parent")
        parent_slug = id_lookup.get(parent_id) if parent_id else None

        payload = {
            "event": "term_updated",
            "taxonomy": taxonomy,
            "term_id": term_id,
            "slug": slug,
            "name": term.get("name") or slug,
            "description": term.get("description") or None,
            "parent_slug": parent_slug,
        }
        await project_term_event(db, payload)
        projected += 1

    return id_to_slug, projected


async def _project_post(
    db,
    post: dict[str, Any],
    slug_lookups: dict[str, dict[int, str]],
) -> str:
    from jobs.wordpress_ingest_projection import project_post_event
    from models.wordpress_event import WordPressEvent
    from sqlalchemy import select

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
    fm_url = (
        post.get("featured_media_url")
        or post.get("jetpack_featured_media_url")
    )

    def _resolve(id_key: str) -> list[str]:
        ids = post.get(id_key) or []
        lookup = slug_lookups.get(id_key, {})
        return [lookup[i] for i in ids if i in lookup]

    payload = {
        "event": "published",
        "post_id": post_id,
        "post_type": post_type,
        "slug": slug,
        "title": title,
        "status": status,
        "modified_gmt": modified_gmt,
        "permalink": permalink,
        "categories": _resolve("categories"),
        "tags": _resolve("tags"),
        "series": _resolve("series"),
        "youtube_video_id": None,
        "featured_media_url": fm_url,
    }

    latest_event_id = (
        await db.execute(
            select(WordPressEvent.id)
            .where(WordPressEvent.post_id == post_id)
            .order_by(WordPressEvent.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none() or 0

    await project_post_event(db, payload, latest_event_id)
    return "projected"


async def run(event: dict[str, Any]) -> dict[str, Any]:
    from database import async_session_maker

    wp_base_url = event.get("wp_base_url") or os.environ.get(
        "WP_BASE_URL", _DEFAULT_WP_BASE_URL
    )
    max_pages = int(event.get("max_pages") or 20)
    dry_run = bool(event.get("dry_run", False))
    taxonomies = event.get("taxonomies") or list(_TAXONOMY_REST_PATH.keys())

    wp_user, wp_app_pw = _load_wp_credentials()
    auth = (wp_user, wp_app_pw) if wp_user and wp_app_pw else None

    log.info(
        "backfill_projection start",
        extra={
            "wp_base_url": wp_base_url,
            "max_pages": max_pages,
            "dry_run": dry_run,
            "taxonomies": taxonomies,
            "authenticated": auth is not None,
        },
    )

    headers = {"User-Agent": _UA}
    term_counts: dict[str, int] = {}
    posts_seen = 0
    posts_projected = 0
    errors = 0

    slug_lookups: dict[str, dict[int, str]] = {}

    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT_S,
        headers=headers,
        follow_redirects=True,
        auth=auth,
    ) as client:
        # Terms first.
        for taxonomy in taxonomies:
            rest_path = _TAXONOMY_REST_PATH.get(taxonomy)
            id_array_key = _POST_TAXONOMY_ID_KEY.get(taxonomy)
            if not rest_path or not id_array_key:
                log.warning("unknown taxonomy skipped", extra={"taxonomy": taxonomy})
                continue

            terms = await _fetch_terms(client, wp_base_url, rest_path)
            log.info(
                "terms fetched",
                extra={"taxonomy": taxonomy, "count": len(terms)},
            )

            if not dry_run and terms:
                async with async_session_maker() as db:
                    try:
                        id_to_slug, projected = await _project_terms_for_taxonomy(
                            db, taxonomy, terms
                        )
                        await db.commit()
                    except Exception as exc:
                        await db.rollback()
                        errors += 1
                        log.warning(
                            "term projection failed",
                            extra={"taxonomy": taxonomy, "error": str(exc)},
                        )
                        id_to_slug, projected = {}, 0
                slug_lookups[id_array_key] = id_to_slug
                term_counts[taxonomy] = projected
            else:
                slug_lookups[id_array_key] = {
                    int(t["id"]): t["slug"] for t in terms
                }
                term_counts[taxonomy] = len(terms)

            await asyncio.sleep(_REQUEST_DELAY_S)

        # Posts second.
        for page in range(1, max_pages + 1):
            posts, status = await _fetch_posts_page(client, wp_base_url, page)
            if status == "empty":
                break
            if status != "ok":
                errors += 1
                await asyncio.sleep(_REQUEST_DELAY_S)
                continue

            posts_seen += len(posts)
            log.info(
                "posts page fetched",
                extra={"page": page, "post_count": len(posts)},
            )

            if not dry_run:
                async with async_session_maker() as db:
                    for post in posts:
                        try:
                            result = await _project_post(db, post, slug_lookups)
                            if result == "projected":
                                posts_projected += 1
                        except Exception as exc:
                            errors += 1
                            log.warning(
                                "post projection failed",
                                extra={
                                    "post_id": post.get("id"),
                                    "error": str(exc),
                                },
                            )
                    await db.commit()

            await asyncio.sleep(_REQUEST_DELAY_S)

    log.info(
        "backfill_projection done",
        extra={
            "term_counts": term_counts,
            "posts_seen": posts_seen,
            "posts_projected": posts_projected,
            "errors": errors,
            "dry_run": dry_run,
        },
    )

    if not dry_run and (posts_projected > 0 or sum(term_counts.values()) > 0):
        from shared.cht_cache import clear_cht_catalog_cache

        clear_cht_catalog_cache(job="wordpress_projection_ops.backfill_projection")

    return {
        "status": "ok",
        "op": "backfill_projection",
        "dry_run": dry_run,
        "term_counts": term_counts,
        "posts_seen": posts_seen,
        "posts_projected": posts_projected,
        "errors": errors,
    }
