"""Unit tests for backend/src/admin/cache.py URL builder and scope handling."""

from __future__ import annotations

import pytest

from admin.cache import _VALID_SCOPES, _build_scoped_url


class TestBuildScopedUrl:
    """Verify the scoped-clear URL derivation across tfvar shapes."""

    def test_modern_url_all(self):
        """Current tfvar shape (.../clear/all) resolves to scoped endpoint."""
        got = _build_scoped_url(
            "https://devapp.communityhealth.media/api/internal/cache/clear/all",
            "contenthub",
            "SECRET",
        )
        assert got == (
            "https://devapp.communityhealth.media/api/internal/cache/clear"
            "?scope=contenthub&cacheKey=SECRET"
        )

    def test_legacy_catalog_url(self):
        """Pre-migration tfvar (.../catalog/clear) still works."""
        got = _build_scoped_url(
            "https://x/api/internal/cache/catalog/clear", "catalog", "S"
        )
        assert got == "https://x/api/internal/cache/clear?scope=catalog&cacheKey=S"

    def test_scope_all(self):
        got = _build_scoped_url(
            "https://x/api/internal/cache/clear/all", "all", "S"
        )
        assert got == "https://x/api/internal/cache/clear?scope=all&cacheKey=S"

    def test_scope_variant_paths(self):
        """Handles clear/<scope> URL shape too."""
        got = _build_scoped_url(
            "https://x/api/internal/cache/clear/contenthub", "contenthub", "S"
        )
        assert got == (
            "https://x/api/internal/cache/clear?scope=contenthub&cacheKey=S"
        )


class TestValidScopes:
    def test_valid_scopes_are_the_three_uche_specd(self):
        assert _VALID_SCOPES == {"catalog", "contenthub", "all"}


@pytest.mark.asyncio
async def test_notify_no_op_when_env_unset(monkeypatch):
    """Empty CHT_CACHE_CLEAR_URL means we skip cleanly, not error."""
    from admin.cache import notify_cht_cache_clear

    monkeypatch.delenv("CHT_CACHE_CLEAR_URL", raising=False)
    monkeypatch.delenv("INTERNAL_CACHE_SECRET", raising=False)
    result = await notify_cht_cache_clear(scope="contenthub")
    assert result is False


@pytest.mark.asyncio
async def test_notify_rejects_invalid_scope(monkeypatch):
    """Invalid scope short-circuits without an HTTP call."""
    from admin.cache import notify_cht_cache_clear

    monkeypatch.setenv("CHT_CACHE_CLEAR_URL", "https://x/api/internal/cache/clear/all")
    monkeypatch.setenv("INTERNAL_CACHE_SECRET", "secret")
    result = await notify_cht_cache_clear(scope="everything")  # type: ignore[arg-type]
    assert result is False
