"""reconcile_drift — one of the ops under wordpress_projection_ops.

Daily standing production defense against mu-plugin webhook drops. Diffs
WordPress source-of-truth against ContentHub's Layer 2 projected state,
emits synthetic signed delete webhooks for any CH-side row not present
on WP. Idempotent, bounded to one reconcile cycle (24h at default cron).

Reconciles:
  1. Post presence — every CH-side live post_id not in WP → synthetic
     `deleted` webhook at own ingress
  2. Term presence — every CH-side non-tombstoned term slug not in WP →
     synthetic `term_deleted` webhook (all 3 taxonomies)
  3. Drift alarm — CloudWatch metric fires when diff exceeds threshold
     BEFORE reconciliation runs

Does NOT reconcile term metadata (that's the backfill_projection op).
Does NOT reconcile M:M memberships (needs synthetic re-publish, out of scope).

Payload:
    {
      "op": "reconcile_drift",
      "wp_base_url": "https://communityhealth.media",
      "max_pages": 20,
      "dry_run": false,
      "drift_alarm_threshold": 20
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
            return seen
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
                "User-Agent": "wordpress_projection_ops.reconcile/1.0",
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
    payload = {
        "event": "term_deleted",
        "taxonomy": taxonomy,
        "term_id": 0,
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
                "User-Agent": "wordpress_projection_ops.reconcile/1.0",
            },
        )
        if resp.status_code >= 400:
            return f"http_{resp.status_code}"
        return "ok"
    except httpx.HTTPError as exc:
        return f"error: {exc}"


def _emit_drift_metric(namespace: str, value: int) -> None:
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


async def run(event: dict[str, Any]) -> dict[str, Any]:
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
        log.warning(
            "SELF_WEBHOOK_URL not configured — reconcile can detect drift "
            "but cannot emit synthetics",
        )

    wp_user, wp_app_pw = _load_wp_credentials()
    auth = (wp_user, wp_app_pw) if wp_user and wp_app_pw else None
    webhook_secret = _load_webhook_secret() if webhook_url else None

    log.info(
        "reconcile_drift start",
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
        # Post reconcile.
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
                await asyncio.sleep(0.2)

        # Term reconcile.
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
        "reconcile_drift done",
        extra={
            "dry_run": dry_run,
            "post_phantoms": len(phantom_ids),
            "post_deletes": post_deletes,
            "term_summary": term_summary,
        },
    )

    return {
        "status": "ok",
        "op": "reconcile_drift",
        "dry_run": dry_run,
        "post_phantoms": len(phantom_ids),
        "post_deletes": post_deletes,
        "term_summary": term_summary,
    }
