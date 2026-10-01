"""CHT upstream cache invalidation helper.

Prefers Cognito M2M Bearer ``platform/cache.clear``. Falls back to
``?cacheKey=<INTERNAL_CACHE_SECRET>`` until that secret is dropped.

Modern endpoint: POST /api/internal/cache/clear?scope=<scope>
See dev.github.tfvars / prod.github.tfvars for the `cht_cache_clear_url` value.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlencode, urlparse, urlunparse

import httpx

log = logging.getLogger(__name__)

CACHE_CLEAR_SCOPE = "platform/cache.clear"


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


def _scoped_clear_url(base_url: str, scope: str) -> str:
    parts = urlparse(base_url)
    path = parts.path.rstrip("/")
    if path.endswith("/clear/all") or path.endswith("/clear/catalog") or path.endswith("/clear/contenthub"):
        path = path[: path.rfind("/clear/") + len("/clear")]
    elif path.endswith("/catalog/clear") or path.endswith("/all/clear") or path.endswith("/contenthub/clear"):
        path = path.rsplit("/", 2)[0] + "/clear"
    return urlunparse(parts._replace(path=path, query=urlencode([("scope", scope)])))


def _m2m_cache_clear_token() -> str:
    try:
        from auth.outbound import fetch_access_token_sync, resolve_outbound_m2m
    except Exception as exc:  # noqa: BLE001
        log.info("CHT cache clear M2M import skipped", extra={"error": str(exc)})
        return ""
    try:
        token_url, client_id, client_secret, scope = resolve_outbound_m2m(
            scope=CACHE_CLEAR_SCOPE
        )
    except Exception as exc:  # noqa: BLE001
        log.info("CHT cache clear M2M resolve skipped", extra={"error": str(exc)})
        return ""
    if not (token_url and client_id and client_secret):
        return ""
    try:
        return fetch_access_token_sync(
            token_url=token_url,
            client_id=client_id,
            client_secret=client_secret,
            scope=scope or CACHE_CLEAR_SCOPE,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("CHT cache clear M2M token failed", extra={"error": str(exc)})
        return ""


def clear_cht_catalog_cache(*, job: str | None = None, scope: str = "contenthub") -> bool:
    """POST to the configured CHT cache-clear endpoint. Returns True on 2xx."""
    url = os.environ.get("CHT_CACHE_CLEAR_URL", "")
    secret = os.environ.get("INTERNAL_CACHE_SECRET", "")
    if not url:
        log.info(
            "CHT cache clear skipped",
            extra={"reason": "CHT_CACHE_CLEAR_URL not set"},
        )
        return False

    token = _m2m_cache_clear_token()
    headers: dict[str, str] = {}
    if token:
        target = _scoped_clear_url(url, scope)
        headers["Authorization"] = f"Bearer {token}"
        auth_mode = "m2m"
    elif secret:
        target = _url_with_cache_key(url, secret)
        auth_mode = "cache_key"
    else:
        log.info(
            "CHT cache clear skipped",
            extra={"reason": "no platform/cache.clear token and INTERNAL_CACHE_SECRET unset"},
        )
        return False

    payload = {"source": "contenthub-sync", "job": job or "cache_clear"}

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(target, json=payload, headers=headers)
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
                "auth": auth_mode,
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
