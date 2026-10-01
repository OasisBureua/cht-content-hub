"""Tests for config and public API dependencies."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from config import Settings, get_settings
from conftest import mint_test_token
from public.deps import verify_public_api_key


def _request(method: str = "GET") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/",
            "headers": [],
            "query_string": b"",
        }
    )


def _m2m_settings() -> Settings:
    return Settings(
        hub_m2m_issuer="https://hub.test",
        hub_m2m_test_secret="test-m2m-hs256",
    )


def test_settings_defaults():
    settings = Settings(public_api_key="test-key")
    assert settings.app_name == "Content Hub API"
    assert settings.public_api_key == "test-key"
    assert settings.db_pool_size == 5


def test_get_settings_cached():
    get_settings.cache_clear()
    first = get_settings()
    second = get_settings()
    assert first is second


def test_verify_public_api_key_valid():
    token = mint_test_token("hub/catalog.read")
    caller = verify_public_api_key(
        _request(), _m2m_settings(), f"Bearer {token}"
    )
    assert caller.startswith("m2m:")


def test_verify_public_api_key_missing():
    with pytest.raises(HTTPException) as exc:
        verify_public_api_key(_request(), _m2m_settings(), None)
    assert exc.value.status_code == 401
    assert exc.value.detail == "Missing bearer token"


def test_verify_public_api_key_invalid():
    with pytest.raises(HTTPException) as exc:
        verify_public_api_key(_request(), _m2m_settings(), "Bearer not-a-jwt")
    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid bearer token"


def test_public_limiter_configured():
    from public.limits import limiter

    assert limiter is not None
    assert callable(limiter._key_func)
