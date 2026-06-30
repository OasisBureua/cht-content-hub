"""cache_clear — invokes CHT POST /internal/cache/catalog/clear."""

from __future__ import annotations

import os


def handler(event: dict, context) -> dict:
    url = os.environ.get("CHT_CACHE_CLEAR_URL", "")
    secret = os.environ.get("INTERNAL_CACHE_SECRET", "")
    if not url or not secret:
        return {"status": "skipped", "reason": "CHT_CACHE_CLEAR_URL or secret not set"}
    # TODO CH-03: httpx POST with X-Internal-Secret header
    return {"status": "not_implemented", "job": "cache_clear", "url": url}
