"""Unit tests for sync/shared/cht_cache.py (the Lambda-side helper).

The sync module lives outside backend/src, but the build-sync-lambda.sh
script copies backend/src into the deployment package so imports work at
runtime. For tests we drive the sync module directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

SYNC_ROOT = Path(__file__).resolve().parents[2] / "sync"
if str(SYNC_ROOT) not in sys.path:
    sys.path.insert(0, str(SYNC_ROOT))

from shared.cht_cache import _url_with_cache_key  # noqa: E402


class TestUrlWithCacheKey:
    def test_appends_cache_key_to_bare_url(self):
        got = _url_with_cache_key(
            "https://devapp.communityhealth.media/api/internal/cache/clear/all",
            "SECRET",
        )
        assert got == (
            "https://devapp.communityhealth.media/api/internal/cache/clear/all"
            "?cacheKey=SECRET"
        )

    def test_preserves_existing_query_params(self):
        got = _url_with_cache_key(
            "https://x/api/internal/cache/clear?scope=all",
            "SECRET",
        )
        assert "scope=all" in got
        assert "cacheKey=SECRET" in got

    def test_replaces_existing_cache_key(self):
        got = _url_with_cache_key(
            "https://x/api/internal/cache/clear/all?cacheKey=OLD&scope=all",
            "NEW",
        )
        assert "cacheKey=OLD" not in got
        assert "cacheKey=NEW" in got
        assert "scope=all" in got
