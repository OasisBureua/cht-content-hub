"""Cache invalidation hook fired after admin writes.

Uses the CHT internal cache API scoped-clear form
(POST /api/internal/cache/clear?scope=<scope>&cacheKey=<secret>) so admin
mutations only invalidate the relevant namespace rather than all caches.

See: https://.../docs/cache-clear-api.md
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlencode, urlparse, urlunparse

import httpx

logger = logging.getLogger("contenthub.admin")


_VALID_SCOPES = {"catalog", "contenthub", "all"}


def _build_scoped_url(base_url: str, scope: str, secret: str) -> str:
    """Derive the scoped-clear URL from the tfvar `cht_cache_clear_url` value.

    The current tfvar points at `.../api/internal/cache/clear/all`. Older
    tfvar values were `.../api/internal/cache/catalog/clear` (legacy path).
    In either case the canonical scoped endpoint is `.../api/internal/cache/clear`
    with `?scope=<scope>&cacheKey=<secret>`.
    """
    parts = urlparse(base_url)
    path = parts.path.rstrip("/")

    # Normalize: peel any trailing /clear/<something-scope-like> or /<X>/clear
    # down to just `.../cache/clear`.
    if path.endswith("/clear/all") or path.endswith("/clear/catalog") or path.endswith("/clear/contenthub"):
        path = path[: path.rfind("/clear/") + len("/clear")]
    elif path.endswith("/catalog/clear") or path.endswith("/all/clear") or path.endswith("/contenthub/clear"):
        # legacy tfvar shape: `.../cache/<scope>/clear` -> `.../cache/clear`
        path = path.rsplit("/", 2)[0] + "/clear"
    # else: path already ends in /clear or something else — pass through.

    query = urlencode([("scope", scope), ("cacheKey", secret)])
    return urlunparse(parts._replace(path=path, query=query))


async def notify_cht_cache_clear(*, scope: str = "contenthub") -> bool:
    """POST CHT scoped cache clear. No-op when URL/secret unset (local dev)."""
    if scope not in _VALID_SCOPES:
        logger.warning("cht cache clear rejected invalid scope", extra={"scope": scope})
        return False

    base = os.environ.get("CHT_CACHE_CLEAR_URL", "")
    secret = os.environ.get("INTERNAL_CACHE_SECRET", "")
    if not base or not secret:
        logger.info(
            "cht cache clear skipped",
            extra={"reason": "CHT_CACHE_CLEAR_URL or INTERNAL_CACHE_SECRET not set"},
        )
        return False

    url = _build_scoped_url(base, scope, secret)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url)
        if response.status_code < 300:
            body = (
                response.json()
                if response.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            logger.info(
                "cht cache cleared",
                extra={
                    "scope": scope,
                    "total_keys_deleted": body.get("total"),
                    "duration_ms": body.get("durationMs"),
                    "enabled": body.get("enabled"),
                },
            )
            return True
        logger.warning(
            "cht cache clear failed",
            extra={
                "scope": scope,
                "status_code": response.status_code,
                "body_preview": response.text[:200],
            },
        )
    except Exception as exc:
        logger.warning(
            "cht cache clear error", extra={"scope": scope, "error": str(exc)}
        )
    return False
