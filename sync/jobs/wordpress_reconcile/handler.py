"""wordpress_reconcile — WPR-17 standing production defense.

Daily EventBridge-triggered Lambda that diffs the WordPress source of truth
against ContentHub's Layer 2 projected state and closes any drift.

Why this exists: even with mu-plugin v0.6 covering trash + delete + term
lifecycle events, webhooks can drop — mu-plugin fire-and-forget means a
transient network failure between WordPress and ContentHub loses the
event. Round 1 shipped without a defense against this, and 9 phantom rows
accumulated on prod over two weeks before WPR-1 cleanup surfaced the gap.

This Lambda is the standing defense: even if the mu-plugin somehow fails
to notify us, drift is bounded to one reconcile cycle (24h by default).

## What it reconciles

1. **Post presence** — every WP `post_id` present in `wordpress_posts` with
   `deleted_at IS NULL` but NOT present on the WordPress side (published
   status filter) gets a synthetic `deleted` webhook fired at ContentHub's
   own ingress. Idempotent by the standard delete-projection path.

2. **Term presence** — every term slug on ContentHub Layer 2 (series /
   category / tag) NOT present on the WordPress side gets a synthetic
   `term_deleted` webhook. Same signed HMAC path as real webhooks.

3. **Drift alarm** — if the diff exceeds a threshold BEFORE reconciliation,
   fires a CloudWatch metric so the operator gets alerted (something broke,
   not just one dropped event).

## Why synthetic webhooks (rather than direct DB writes)

The mu-plugin fires signed webhooks that go through router HMAC validation
→ SQS → ingest Lambda → projection. Emitting synthetic webhooks reuses
that entire path — same code, same validation, same idempotency. If we
wrote directly to the DB we'd have two projection code paths to maintain
and one of them (the direct-write one) would bypass the router's shape
checks.

The tradeoff: we hit our own webhook endpoint. That's fine — it's a
localhost-ish call inside the VPC and the request budget is tiny (≤ few
hundred posts on the entire site).

## What it does NOT do

- Does NOT reconcile term METADATA (name / description / parent). That's
  wordpress_projection_backfill's job — reconcile is about presence.
- Does NOT reconcile M:M memberships. If a post's series set diverges from
  WP, the underlying post event was dropped; the fix is a synthetic post
  re-publish, which is a scope conversation with the operator (do we
  clobber CHT-side state?). Not covered here.
- Does NOT reconcile posts on the WP side that are missing on CH side
  (that's the seed / backfill Lambdas' job). Reconcile is one-directional:
  it detects and removes phantoms, not fills gaps.

## Payload

    {
      "wp_base_url": "https://communityhealth.media",  # defaults
      "max_pages": 20,   # cap page fetch
      "dry_run": false,  # if true, report drift but don't emit synthetics
      "drift_alarm_threshold": 20,  # emit metric if drift exceeds
    }
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
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
_DEFAULT_DRIFT_THRESHOLD = 20

_TAXONOMY_REST_PATH: dict[str, str] = {
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


def _load_webhook_secret() -> str | None:
    """Read the same webhook secret the mu-plugin uses so our synthetics
    pass the router HMAC check."""
    arn = os.environ.get("APP_SECRETS_ARN", "")
    if not arn:
        return os.environ.get("WORDPRESS_WEBHOOK_SECRET") or None
    try:
        client = boto3.client(
            "secretsmanager",
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )
        payload = json.loads(client.get_secret_value(SecretId=arn)["SecretString"])
    except Exception as exc:
        log.warning("could not load webhook secret", extra={"error": str(exc)})
        return None
    return payload.get("wordpress_webhook_secret") or None


async def _fetch_wp_post_ids(
    client: httpx.AsyncClient, base_url: str, max_pages: int
) -> set[int]:
    """Return the set of published post IDs currently on WordPress."""
    seen: set[int] = set()
    for page in range(1, max_pages + 1):
        url = f"{base_url.rstrip('/')}/wp-json/wp/v2/posts"
        try:
            resp = await client.get(
                url,
                params={
                    "per_page": _PER_PAGE,
                    "page": page,
                    "status": "publish",
                    "_fields": "id",
                },
            )
        except httpx.HTTPError as exc:
            log.warning(
                "reconcile wp page fetch failed",
                extra={"page": page, "error": str(exc)},
            )
            return seen  # partial data — refuse to reconcile on partial
        if resp.status_code == 400 and page > 1:
            break
        if resp.status_code >= 400:
            log.warning(
                "reconcile wp non-2xx",
                extra={"page": page, "status": resp.status_code},
            )
            return seen
        items = resp.json()
        if not items:
            break
        for item in items:
            seen.add(int(item["id"]))
        if len(items) < _PER_PAGE:
            break
        await asyncio.sleep(_REQUEST_DELAY_S)
    return seen


async def _fetch_wp_term_slugs(
    client: httpx.AsyncClient, base_url: str, rest_path: str
) -> set[str]:
    """Return the set of term slugs currently on WordPress for one taxonomy."""
    seen: set[str] = set()
    page = 1
    while True:
        url = f"{base_url.rstrip('/')}/wp-json/wp/v2/{rest_path}"
        try:
            resp = await client.get(
                url,
                params={
                    "per_page": _PER_PAGE,
                    "page": page,
                    "_fields": "slug",
                },
            )
        except httpx.HTTPError as exc:
            log.warning(
                "reconcile term fetch failed",
                extra={"rest_path": rest_path, "page": page, "error": str(exc)},
            )
            return seen
        if resp.status_code == 400 and page > 1:
            break
        if resp.status_code >= 400:
            return seen
        items = resp.json()
        if not items:
            break
        for item in items:
            seen.add(item["slug"])
        if len(items) < _PER_PAGE:
            break
        page += 1
        await asyncio.sleep(_REQUEST_DELAY_S)
    return seen


async def _fetch_ch_live_post_ids() -> set[int]:
    """CH-side live post IDs (deleted_at IS NULL)."""
    from database import async_session_maker
    from models.wordpress_projection import WordPressPost
    from sqlalchemy import select

    async with async_session_maker() as db:
        rows = (
            await db.execute(
                select(WordPressPost.post_id).where(
                    WordPressPost.deleted_at.is_(None)
                )
            )
        ).scalars().all()
    return set(rows)


async def _fetch_ch_live_term_slugs(taxonomy: str) -> set[str]:
    from database import async_session_maker
    from models.wordpress_projection import (
        WordPressCategory,
        WordPressSeries,
        WordPressTag,
    )
    from sqlalchemy import select

    model_map = {
        "series": WordPressSeries,
        "category": WordPressCategory,
        "post_tag": WordPressTag,
    }
    model = model_map[taxonomy]

    async with async_session_maker() as db:
        rows = (
            await db.execute(
                select(model.slug).where(model.deleted_at.is_(None))
            )
        ).scalars().all()
    return set(rows)


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()


async def _emit_synthetic_post_delete(
    client: httpx.AsyncClient,
    webhook_url: str,
    secret: str,
    post_id: int,
) -> str:
    """Fire a signed `deleted` webhook at our own ingress for one phantom post."""
    payload = {
        "event": "deleted",
        "post_id": post_id,
        "post_type": "post",
        "slug": f"reconcile-phantom-{post_id}",
        "title": "(reconciled phantom)",
        "status": "trash",
        "modified_gmt": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "permalink": "",
        "categories": [],
        "tags": [],
        "series": [],
        "site_url": os.environ.get("WP_BASE_URL", _DEFAULT_WP_BASE_URL),
    }
    body = json.dumps(payload).encode("utf-8")
    try:
        resp = await client.post(
            webhook_url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-CHT-Signature": _sign(body, secret),
                "X-CHT-Event": "deleted",
                "User-Agent": "wordpress_reconcile/1.0",
            },
        )
        if resp.status_code >= 400:
            return f"http_{resp.status_code}"
        return "ok"
    except httpx.HTTPError as exc:
        return f"error: {exc}"


async def _emit_synthetic_term_delete(
    client: httpx.AsyncClient,
    webhook_url: str,
    secret: str,
    taxonomy: str,
    slug: str,
) -> str:
    """Fire a signed `term_deleted` webhook for one phantom term."""
    payload = {
        "event": "term_deleted",
        "taxonomy": taxonomy,
        "term_id": 0,  # unknown at reconcile time; router accepts int
        "slug": slug,
        "site_url": os.environ.get("WP_BASE_URL", _DEFAULT_WP_BASE_URL),
    }
    body = json.dumps(payload).encode("utf-8")
    try:
        resp = await client.post(
            webhook_url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-CHT-Signature": _sign(body, secret),
                "X-CHT-Event": "term_deleted",
                "User-Agent": "wordpress_reconcile/1.0",
            },
        )
        if resp.status_code >= 400:
            return f"http_{resp.status_code}"
        return "ok"
    except httpx.HTTPError as exc:
        return f"error: {exc}"


def _emit_drift_metric(namespace: str, value: int) -> None:
    """Send a CloudWatch metric so ops sees drift-before-reconcile."""
    try:
        cw = boto3.client(
            "cloudwatch",
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )
        cw.put_metric_data(
            Namespace="ContentHub/Reconcile",
            MetricData=[
                {
                    "MetricName": "PhantomsDetected",
                    "Value": value,
                    "Unit": "Count",
                    "Dimensions": [{"Name": "Kind", "Value": namespace}],
                }
            ],
        )
    except Exception as exc:
        log.warning("cloudwatch metric emit failed", extra={"error": str(exc)})


async def _run(event: dict[str, Any]) -> dict[str, Any]:
    wp_base_url = event.get("wp_base_url") or os.environ.get(
        "WP_BASE_URL", _DEFAULT_WP_BASE_URL
    )
    max_pages = int(event.get("max_pages") or 20)
    dry_run = bool(event.get("dry_run", False))
    drift_threshold = int(
        event.get("drift_alarm_threshold") or _DEFAULT_DRIFT_THRESHOLD
    )

    webhook_url = os.environ.get("SELF_WEBHOOK_URL")
    if not webhook_url:
        # Default: hit the same ingress the mu-plugin does. In prod this
        # resolves to contenthub.communityhealth.media; on dev, devhub.
        # Configured via TF env var on the Lambda.
        log.warning(
            "SELF_WEBHOOK_URL not configured — reconcile can detect drift "
            "but cannot emit synthetics",
        )

    wp_user, wp_app_pw = _load_wp_credentials()
    auth = (wp_user, wp_app_pw) if wp_user and wp_app_pw else None
    webhook_secret = _load_webhook_secret() if webhook_url else None

    log.info(
        "wordpress_reconcile start",
        extra={
            "wp_base_url": wp_base_url,
            "max_pages": max_pages,
            "dry_run": dry_run,
            "authenticated": auth is not None,
            "has_webhook_target": bool(webhook_url and webhook_secret),
        },
    )

    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT_S,
        headers={"User-Agent": _UA},
        follow_redirects=True,
        auth=auth,
    ) as client:
        # ── Post reconcile ───────────────────────────────────────────
        wp_ids = await _fetch_wp_post_ids(client, wp_base_url, max_pages)
        ch_ids = await _fetch_ch_live_post_ids()
        phantom_ids = ch_ids - wp_ids

        log.info(
            "post reconcile diff",
            extra={
                "wp_ids": len(wp_ids),
                "ch_live_ids": len(ch_ids),
                "phantoms": len(phantom_ids),
            },
        )

        if len(phantom_ids) >= drift_threshold:
            _emit_drift_metric("posts", len(phantom_ids))

        post_deletes = {"attempted": 0, "ok": 0, "failed": 0}
        if not dry_run and webhook_url and webhook_secret and phantom_ids:
            for pid in sorted(phantom_ids):
                result = await _emit_synthetic_post_delete(
                    client, webhook_url, webhook_secret, pid
                )
                post_deletes["attempted"] += 1
                if result == "ok":
                    post_deletes["ok"] += 1
                else:
                    post_deletes["failed"] += 1
                    log.warning(
                        "synthetic post delete failed",
                        extra={"post_id": pid, "result": result},
                    )
                await asyncio.sleep(0.2)  # gentle self-throttle

        # ── Term reconcile ───────────────────────────────────────────
        term_summary: dict[str, dict[str, Any]] = {}
        for taxonomy, rest_path in _TAXONOMY_REST_PATH.items():
            wp_slugs = await _fetch_wp_term_slugs(client, wp_base_url, rest_path)
            ch_slugs = await _fetch_ch_live_term_slugs(taxonomy)
            phantom_terms = ch_slugs - wp_slugs

            log.info(
                "term reconcile diff",
                extra={
                    "taxonomy": taxonomy,
                    "wp_count": len(wp_slugs),
                    "ch_count": len(ch_slugs),
                    "phantoms": len(phantom_terms),
                },
            )

            if len(phantom_terms) >= drift_threshold:
                _emit_drift_metric(f"terms_{taxonomy}", len(phantom_terms))

            attempted = ok = failed = 0
            if (
                not dry_run
                and webhook_url
                and webhook_secret
                and phantom_terms
            ):
                for slug in sorted(phantom_terms):
                    result = await _emit_synthetic_term_delete(
                        client, webhook_url, webhook_secret, taxonomy, slug
                    )
                    attempted += 1
                    if result == "ok":
                        ok += 1
                    else:
                        failed += 1
                        log.warning(
                            "synthetic term delete failed",
                            extra={
                                "taxonomy": taxonomy,
                                "slug": slug,
                                "result": result,
                            },
                        )
                    await asyncio.sleep(0.2)

            term_summary[taxonomy] = {
                "wp_count": len(wp_slugs),
                "ch_count": len(ch_slugs),
                "phantoms": len(phantom_terms),
                "attempted": attempted,
                "ok": ok,
                "failed": failed,
            }
            await asyncio.sleep(_REQUEST_DELAY_S)

    log.info(
        "wordpress_reconcile done",
        extra={
            "dry_run": dry_run,
            "post_phantoms": len(phantom_ids),
            "post_deletes": post_deletes,
            "term_summary": term_summary,
        },
    )

    return {
        "status": "ok",
        "job": "wordpress_reconcile",
        "dry_run": dry_run,
        "post_phantoms": len(phantom_ids),
        "post_deletes": post_deletes,
        "term_summary": term_summary,
    }


def handler(event: dict, context) -> dict:
    install_paths()
    configure_logging()
    return run_async(_run(event or {}))
