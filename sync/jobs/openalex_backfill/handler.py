"""hcp_intel_openalex_backfill — resolve HCPs to OpenAlex author IDs."""

from __future__ import annotations

from shared.runtime import configure_logging, install_paths, run_async


async def _run(event: dict) -> dict:
    from hcp_intel.openalex_backfill import backfill

    limit = event.get("limit")
    batch_size = int(event.get("batch_size", 50))
    counts = await backfill(limit=limit, batch_size=batch_size)
    return {"status": "ok", "job": "hcp_intel_openalex_backfill", **counts}


def handler(event: dict, context) -> dict:
    install_paths()
    configure_logging()
    payload = event or {}
    if "Records" in payload and payload["Records"]:
        import json

        body = payload["Records"][0].get("body", "{}")
        try:
            payload = json.loads(body) if isinstance(body, str) else body
        except json.JSONDecodeError:
            payload = {}
    return run_async(_run(payload))
