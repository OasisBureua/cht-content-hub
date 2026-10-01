"""Cache invalidation hook fired after admin writes.

Prefers Cognito M2M Bearer ``platform/cache.clear`` on
``POST /api/internal/cache/clear?scope=<scope>``. Falls back to the legacy
``?cacheKey=<INTERNAL_CACHE_SECRET>`` query so dual-run stays safe until
that GitHub/SM secret is dropped.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlencode, urlparse, urlunparse

import httpx

from auth.outbound import CACHE_CLEAR_SCOPE, fetch_access_token, resolve_outbound_m2m

logger = logging.getLogger("contenthub.admin")


_VALID_SCOPES = {"catalog", "contenthub", "all"}


def _build_scoped_url(base_url: str, scope: str, secret: str = "") -> str:
    """Derive the scoped-clear URL from the tfvar `cht_cache_clear_url` value.

    The current tfvar points at `.../api/internal/cache/clear/all`. Older
    tfvar values were `.../api/internal/cache/catalog/clear` (legacy path).
    In either case the canonical scoped endpoint is `.../api/internal/cache/clear`
    with `?scope=<scope>` and optional `cacheKey` for the legacy secret.
    """
    parts = urlparse(base_url)
    path = parts.path.rstrip("/")

    if path.endswith("/clear/all") or path.endswith("/clear/catalog") or path.endswith("/clear/contenthub"):
        path = path[: path.rfind("/clear/") + len("/clear")]
    elif path.endswith("/catalog/clear") or path.endswith("/all/clear") or path.endswith("/contenthub/clear"):
        path = path.rsplit("/", 2)[0] + "/clear"

    query = [("scope", scope)]
    if secret:
        query.append(("cacheKey", secret))
    return urlunparse(parts._replace(path=path, query=urlencode(query)))


async def _m2m_cache_clear_token() -> str:
    try:
        token_url, client_id, client_secret, scope = resolve_outbound_m2m(
            scope=CACHE_CLEAR_SCOPE
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("cht cache clear M2M resolve skipped", extra={"error": str(exc)})
        return ""
    if not (token_url and client_id and client_secret):
        return ""
    try:
        return await fetch_access_token(
            token_url=token_url,
            client_id=client_id,
            client_secret=client_secret,
            scope=scope or CACHE_CLEAR_SCOPE,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("cht cache clear M2M token failed", extra={"error": str(exc)})
        return ""


async def notify_cht_cache_clear(*, scope: str = "contenthub") -> bool:
    """POST CHT scoped cache clear. No-op when URL and both auth modes unset."""
    if scope not in _VALID_SCOPES:
        logger.warning("cht cache clear rejected invalid scope", extra={"scope": scope})
        return False

    base = os.environ.get("CHT_CACHE_CLEAR_URL", "")
    secret = os.environ.get("INTERNAL_CACHE_SECRET", "")
    if not base:
        logger.info(
            "cht cache clear skipped",
            extra={"reason": "CHT_CACHE_CLEAR_URL not set"},
        )
        return False

    token = await _m2m_cache_clear_token()
    headers: dict[str, str] = {}
    if token:
        url = _build_scoped_url(base, scope)
        headers["Authorization"] = f"Bearer {token}"
        auth_mode = "m2m"
    elif secret:
        url = _build_scoped_url(base, scope, secret)
        auth_mode = "cache_key"
    else:
        logger.info(
            "cht cache clear skipped",
            extra={"reason": "no platform/cache.clear token and INTERNAL_CACHE_SECRET unset"},
        )
        return False

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, headers=headers)
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
                    "auth": auth_mode,
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
                "auth": auth_mode,
                "status_code": response.status_code,
                "body_preview": response.text[:200],
            },
        )
    except Exception as exc:
        logger.warning(
            "cht cache clear error", extra={"scope": scope, "error": str(exc)}
        )
    return False
