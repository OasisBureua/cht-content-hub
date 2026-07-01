"""Tests for config and public API dependencies."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from config import Settings, get_settings
from public.deps import verify_public_api_key


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
    settings = Settings(public_api_key="good-key")
    assert verify_public_api_key(settings, "good-key") == "good-key"


def test_verify_public_api_key_missing():
    settings = Settings(public_api_key="good-key")
    with pytest.raises(HTTPException) as exc:
        verify_public_api_key(settings, None)
    assert exc.value.status_code == 401
    assert exc.value.detail == "Missing API key"


def test_verify_public_api_key_invalid():
    settings = Settings(public_api_key="good-key")
    with pytest.raises(HTTPException) as exc:
        verify_public_api_key(settings, "bad-key")
    assert exc.value.status_code == 401


def test_public_limiter_configured():
    from public.limits import limiter

    assert limiter is not None
    assert callable(limiter._key_func)
