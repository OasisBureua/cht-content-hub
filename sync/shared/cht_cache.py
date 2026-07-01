"""CHT catalog cache invalidation helper."""

from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger(__name__)


def clear_cht_catalog_cache(*, job: str | None = None) -> bool:
    """POST to CHT /internal/cache/catalog/clear. Returns True on 2xx."""
    url = os.environ.get("CHT_CACHE_CLEAR_URL", "")
    secret = os.environ.get("INTERNAL_CACHE_SECRET", "")
    if not url or not secret:
        log.info("CHT cache clear skipped (CHT_CACHE_CLEAR_URL or secret not set)")
        return False
    payload = {"source": "contenthub-sync", "job": job or "cache_clear"}
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                url,
                headers={"X-Internal-Secret": secret},
                json=payload,
            )
            resp.raise_for_status()
        log.info("CHT cache cleared job=%s", job)
        return True
    except Exception as exc:
        log.warning("CHT cache clear failed job=%s: %s", job, exc)
        return False
