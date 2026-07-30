"""wordpress_projection_backfill — one-shot Lambda that hydrates Layer 2.

Complementary to `wordpress_seed` (which populates Layer 1 event log via
INSERT into wordpress_events). This job populates Layer 2 projected-state
tables — wordpress_posts, wordpress_series, wordpress_categories,
wordpress_tags, and their M:M association tables — by querying WordPress
REST for canonical term metadata + post↔term membership.

Design:

- Fetches full term inventories for the three taxonomies (`series` custom
  taxonomy, `categories`, `tags`) with name + description + parent + term_id.
- Fetches all published posts with their category / tag / series ID arrays.
- Resolves those IDs to slugs against the term inventory.
- Feeds each term into `project_term_event(payload)` — same projection code
  the ingest Lambda uses for real-time term-lifecycle events, so this
  backfill converges to the same state a full replay would produce.
- Feeds each post into `project_post_event(payload, event_id)` — same
  projection code the ingest Lambda uses for post events. Uses the most
  recent matching wordpress_events.id as event_id (or 0 if no event exists).

Idempotent by construction: term + post projection are UPSERT-based, M:M
membership reconcile is set-based. Re-invocation converges to identical
state without duplicating rows.

Ordering: terms first, then posts. This guarantees the FK from
wordpress_post_series → wordpress_series is satisfied even before the
projection's own defensive UPSERT would kick in.

Auth: WordPress Application Password from Secrets Manager (same
`wordpress_admin_user` + `wordpress_admin_app_password` keys used by
wordpress_seed).

Rate limited: 1 req/sec cadence to respect WP's WAF ceiling.

Invocation:
    aws lambda invoke \\
      --function-name contenthub-dev-sync-wordpress-projection-backfill \\
      --payload '{}' \\
      /tmp/resp.json && cat /tmp/resp.json

Payload (all optional):
    {
      "wp_base_url": "https://communityhealth.media",  # defaults
      "max_pages": 20,   # cap post pages to fetch this invoke
      "taxonomies": ["series", "category", "post_tag"],  # subset for partial re-runs
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

from shared.runtime import configure_logging, install_paths, run_async

log = logging.getLogger(__name__)

_DEFAULT_WP_BASE_URL = "https://communityhealth.media"
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_PER_PAGE = 100
_REQUEST_DELAY_S = 1.0
_HTTP_TIMEOUT_S = 20.0

# Maps ContentHub taxonomy identifier → WP REST endpoint path.
# WordPress's REST base for the built-in taxonomies is /categories + /tags;
# the custom `series` taxonomy is exposed at /series when the plugin that
# registers it also enables `show_in_rest` (Andrew's config does).
_TAXONOMY_REST_PATH: dict[str, str] = {
    "series": "series",
    "category": "categories",
    "post_tag": "tags",
}

# WordPress uses these keys on `posts` responses for the ID arrays. Map to
# our internal taxonomy identifier.
_POST_TAXONOMY_ID_KEY: dict[str, str] = {
    "series": "series",  # `series` custom taxonomy exposes an ID array too
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
    """Return the full term inventory for one taxonomy from WP REST.

    Includes name + description + parent + wp_term_id — everything the
    projection layer needs.
    """
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
    """Fetch one page of posts with the ID arrays needed for membership."""
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
    """Project every term into Layer 2. Returns (id→slug map, projected count).

    Also builds an id→slug lookup used later to translate post ID arrays
    into slug arrays for the M:M projection.
    """
    from jobs.wordpress_ingest_projection import project_term_event

    id_to_slug: dict[int, str] = {}
    projected = 0

    # Build parent_id→slug lookup so parent_slug references can be resolved.
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
    """Project one WP post into Layer 2. Returns 'projected' or 'skipped'."""
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
        "youtube_video_id": None,  # extraction is mu-plugin's job; backfill leaves NULL
        "featured_media_url": fm_url,
    }

    # Use the latest wordpress_events.id for this post_id if one exists —
    # keeps Layer 2's last_event_id back-reference honest. Otherwise 0
    # sentinel means "projected by backfill without a matching event".
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


async def _run(event: dict[str, Any]) -> dict[str, Any]:
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
        "wordpress_projection_backfill start",
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

    # Post's per-taxonomy ID arrays use these keys; we build slug lookups
    # keyed by that ID-array key (categories/tags/series).
    slug_lookups: dict[str, dict[int, str]] = {}

    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT_S,
        headers=headers,
        follow_redirects=True,
        auth=auth,
    ) as client:
        # ── Terms first ──────────────────────────────────────────────
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
                # Dry run — still build the lookup for post projection preview.
                slug_lookups[id_array_key] = {
                    int(t["id"]): t["slug"] for t in terms
                }
                term_counts[taxonomy] = len(terms)

            await asyncio.sleep(_REQUEST_DELAY_S)

        # ── Posts second ─────────────────────────────────────────────
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
        "wordpress_projection_backfill done",
        extra={
            "term_counts": term_counts,
            "posts_seen": posts_seen,
            "posts_projected": posts_projected,
            "errors": errors,
            "dry_run": dry_run,
        },
    )

    # Cache-clear so CHT picks up the newly-projected state immediately.
    if not dry_run and (posts_projected > 0 or sum(term_counts.values()) > 0):
        from shared.cht_cache import clear_cht_catalog_cache

        clear_cht_catalog_cache(job="wordpress_projection_backfill")

    return {
        "status": "ok",
        "job": "wordpress_projection_backfill",
        "dry_run": dry_run,
        "term_counts": term_counts,
        "posts_seen": posts_seen,
        "posts_projected": posts_projected,
        "errors": errors,
    }


def handler(event: dict, context) -> dict:
    install_paths()
    configure_logging()
    return run_async(_run(event or {}))
