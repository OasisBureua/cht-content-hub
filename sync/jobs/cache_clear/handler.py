"""cache_clear — invokes CHT POST /internal/cache/catalog/clear."""

from __future__ import annotations

from shared.cht_cache import clear_cht_catalog_cache
from shared.runtime import configure_logging, install_paths


def handler(event: dict, context) -> dict:
    install_paths()
    configure_logging()
    job = (event or {}).get("job")
    cleared = clear_cht_catalog_cache(job=job)
    return {"status": "ok" if cleared else "skipped", "job": job or "cache_clear"}
