"""CHT upstream cache invalidation helper.

Modern endpoint: POST /api/internal/cache/clear/all
See dev.github.tfvars / prod.github.tfvars for the `cht_cache_clear_url` value.

Auth uses the query-parameter form `?cacheKey=<secret>` (preferred per the
CHT internal cache API spec). The legacy `x-internal-secret` header is also
accepted server-side but query param is the recommended path for new sync jobs.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlencode, urlparse, urlunparse

import httpx

log = logging.getLogger(__name__)


def _url_with_cache_key(url: str, secret: str) -> str:
    """Append/replace cacheKey query parameter without disturbing other params."""
    parts = urlparse(url)
    existing = [
        (k, v)
        for k, v in (
            tuple(p.split("=", 1)) if "=" in p else (p, "")
            for p in parts.query.split("&")
            if p
        )
        if k != "cacheKey"
    ]
    existing.append(("cacheKey", secret))
    return urlunparse(parts._replace(query=urlencode(existing)))


def clear_cht_catalog_cache(*, job: str | None = None) -> bool:
    """POST to the configured CHT cache-clear endpoint. Returns True on 2xx."""
    url = os.environ.get("CHT_CACHE_CLEAR_URL", "")
    secret = os.environ.get("INTERNAL_CACHE_SECRET", "")
    if not url or not secret:
        log.info(
            "CHT cache clear skipped",
            extra={"reason": "CHT_CACHE_CLEAR_URL or INTERNAL_CACHE_SECRET not set"},
        )
        return False

    signed_url = _url_with_cache_key(url, secret)
    payload = {"source": "contenthub-sync", "job": job or "cache_clear"}

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(signed_url, json=payload)
            resp.raise_for_status()
        body = (
            resp.json()
            if resp.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        log.info(
            "CHT cache cleared",
            extra={
                "job": job,
                "scope": body.get("scope"),
                "total_keys_deleted": body.get("total"),
                "duration_ms": body.get("durationMs"),
                "enabled": body.get("enabled"),
            },
        )
        return True
    except Exception as exc:
        log.warning("CHT cache clear failed", extra={"job": job, "error": str(exc)})
        return False
