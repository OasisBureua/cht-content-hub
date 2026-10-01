"""Shared outbound M2M token cache + interceptor."""

from __future__ import annotations

import httpx
import pytest

from auth.outbound import (
    CachedBearerAuth,
    TokenCache,
    fetch_access_token,
    reset_shared_token_cache,
    warm_outbound_tokens,
)
from config import Settings


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_shared_token_cache()
    yield
    reset_shared_token_cache()


@pytest.mark.asyncio
async def test_fetch_access_token_caches_second_call():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200, json={"access_token": "cached-tok", "expires_in": 3600}
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        first = await fetch_access_token(
            token_url="https://idp.test/oauth2/token",
            client_id="hub",
            client_secret="secret",
            scope="platform/export.read",
            http=http,
        )
        second = await fetch_access_token(
            token_url="https://idp.test/oauth2/token",
            client_id="hub",
            client_secret="secret",
            scope="platform/export.read",
            http=http,
        )

    assert first == second == "cached-tok"
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_cached_bearer_auth_sets_header():
    def token_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"access_token": "plat-tok", "expires_in": 3600}
        )

    def api_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer plat-tok"
        return httpx.Response(200, json={"ok": True})

    cache = TokenCache()
    transport = httpx.MockTransport(token_handler)
    async with httpx.AsyncClient(transport=transport) as token_http:
        await fetch_access_token(
            token_url="https://idp.test/oauth2/token",
            client_id="hub",
            client_secret="secret",
            scope="platform/export.read",
            cache=cache,
            http=token_http,
        )

    auth = CachedBearerAuth(
        token_url="https://idp.test/oauth2/token",
        client_id="hub",
        client_secret="secret",
        scope="platform/export.read",
        cache=cache,
    )
    transport = httpx.MockTransport(api_handler)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://platform.test", auth=auth
    ) as http:
        r = await http.get("/api/export/ping")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_warm_skips_when_unconfigured():
    await warm_outbound_tokens(Settings())
