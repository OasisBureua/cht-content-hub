"""Outbound M2M: in-memory token cache + httpx interceptor for platform calls.

Hub's client requests *platform* scopes (not hub/*). Tokens are fetched once
via client_credentials, cached until near expiry, and attached as
``Authorization: Bearer`` on every platform HTTP request.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

_SKEW_SECONDS = 60.0


class TokenCache:
    """Process-local cache: scope -> (access_token, expires_at_unix)."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._entries: dict[str, tuple[str, float]] = {}

    def clear(self) -> None:
        self._entries.clear()

    def peek(self, scope: str) -> str | None:
        token, expires_at = self._entries.get(scope, ("", 0.0))
        if token and time.time() < expires_at - _SKEW_SECONDS:
            return token
        return None

    async def get_or_set(
        self,
        scope: str,
        fetcher,
        *,
        force: bool = False,
    ) -> str:
        async with self._lock:
            if not force:
                cached = self.peek(scope)
                if cached:
                    return cached
            token, expires_at = await fetcher()
            self._entries[scope] = (token, expires_at)
            return token


_shared = TokenCache()


def shared_token_cache() -> TokenCache:
    return _shared


def reset_shared_token_cache() -> None:
    _shared.clear()


async def fetch_access_token(
    *,
    token_url: str,
    client_id: str,
    client_secret: str,
    scope: str,
    cache: TokenCache | None = None,
    http: httpx.AsyncClient | None = None,
    force: bool = False,
) -> str:
    """Return a cached access token, refreshing when missing/expired/forced."""
    if not (token_url and client_id and client_secret):
        raise RuntimeError(
            "Outbound M2M is not configured "
            "(token_url + client_id + client_secret required)"
        )
    store = cache if cache is not None else _shared
    owns_http = http is None
    client = http or httpx.AsyncClient(timeout=15.0)

    async def _fetch() -> tuple[str, float]:
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        response = await client.post(
            token_url,
            data={"grant_type": "client_credentials", "scope": scope},
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        if response.status_code in (401, 403):
            raise RuntimeError(
                f"M2M token request failed with HTTP {response.status_code}"
            )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        token = payload.get("access_token")
        if not token:
            raise RuntimeError("M2M token response missing access_token")
        try:
            expires_at = time.time() + float(payload.get("expires_in") or 3600)
        except (TypeError, ValueError):
            expires_at = time.time() + 3600
        return str(token), expires_at

    try:
        return await store.get_or_set(scope, _fetch, force=force)
    finally:
        if owns_http:
            await client.aclose()


class CachedBearerAuth(httpx.Auth):
    """httpx interceptor: Bearer from cache; refresh once on 401."""

    def __init__(
        self,
        *,
        token_url: str,
        client_id: str,
        client_secret: str,
        scope: str,
        cache: TokenCache | None = None,
    ) -> None:
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        self.cache = cache if cache is not None else _shared

    def _is_token_request(self, request: httpx.Request) -> bool:
        target = (self.token_url or "").rstrip("/")
        url = str(request.url)
        return bool(target) and url.startswith(target)

    async def async_auth_flow(self, request: httpx.Request):
        if self._is_token_request(request):
            yield request
            return
        token = await fetch_access_token(
            token_url=self.token_url,
            client_id=self.client_id,
            client_secret=self.client_secret,
            scope=self.scope,
            cache=self.cache,
        )
        request.headers["Authorization"] = f"Bearer {token}"
        response = yield request
        if response.status_code == 401:
            token = await fetch_access_token(
                token_url=self.token_url,
                client_id=self.client_id,
                client_secret=self.client_secret,
                scope=self.scope,
                cache=self.cache,
                force=True,
            )
            request.headers["Authorization"] = f"Bearer {token}"
            yield request


async def warm_outbound_tokens(settings) -> None:
    """Prefetch Hub→platform token at API startup. Never fails startup."""
    from services.export_ingest.m2m_secrets import resolve_m2m_settings_fields

    try:
        token_url, client_id, client_secret, scope = resolve_m2m_settings_fields(
            secret_arn=(settings.platform_export_m2m_secret_arn or "").strip(),
            token_url=settings.platform_export_token_url,
            client_id=settings.platform_export_client_id,
            client_secret=settings.platform_export_client_secret,
            scope=settings.platform_export_scope or "platform/export.read",
            region_name=settings.aws_region,
        )
    except Exception as exc:  # noqa: BLE001
        log.info("Outbound M2M warm skipped: %s", exc)
        return
    if not (token_url and client_id and client_secret):
        log.info("Outbound M2M warm skipped: credentials not set")
        return
    try:
        await fetch_access_token(
            token_url=token_url,
            client_id=client_id,
            client_secret=client_secret,
            scope=scope,
        )
        log.info("Outbound M2M token cached scope=%s", scope)
    except Exception as exc:  # noqa: BLE001
        log.warning("Outbound M2M warm failed: %s", exc)
