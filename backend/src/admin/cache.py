"""Placeholder cache invalidation hook after admin writes."""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger("contenthub.admin")


async def notify_cht_cache_clear(*, scope: str = "contenthub") -> bool:
    """POST CHT /api/internal/cache/clear — no-op when URL unset (local dev)."""
    base = os.environ.get("CHT_CACHE_CLEAR_URL", "").rstrip("/")
    secret = os.environ.get("INTERNAL_CACHE_SECRET", "")
    if not base or not secret:
        logger.info("cht cache clear skipped (CHT_CACHE_CLEAR_URL or secret not set)")
        return False

    url = base if base.endswith("/clear") else f"{base.rstrip('/')}/clear"
    if "?" not in url:
        url = f"{url}?scope={scope}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {secret}"},
            )
        if response.status_code < 300:
            logger.info("cht cache cleared scope=%s", scope)
            return True
        logger.warning(
            "cht cache clear failed status=%s body=%s",
            response.status_code,
            response.text[:200],
        )
    except Exception as exc:
        logger.warning("cht cache clear error: %s", exc)
    return False
