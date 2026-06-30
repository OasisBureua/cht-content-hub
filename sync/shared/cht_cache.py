"""CHT catalog cache invalidation helper."""

from __future__ import annotations

import os


def clear_cht_catalog_cache() -> bool:
    """POST to CHT /internal/cache/catalog/clear. Returns True on 2xx."""
    url = os.environ.get("CHT_CACHE_CLEAR_URL", "")
    secret = os.environ.get("INTERNAL_CACHE_SECRET", "")
    if not url or not secret:
        return False
    # TODO CH-03: httpx implementation
    return False
