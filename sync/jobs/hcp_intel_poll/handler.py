"""hcp_intel_poll — poll due HCP feed subscriptions."""

from __future__ import annotations

import json

from shared.runtime import configure_logging, install_paths, run_async


def _parse_event(event: dict) -> dict:
    if not event:
        return {}
    if "Records" in event and event["Records"]:
        record = event["Records"][0]
        body = record.get("body", "{}")
        try:
            return json.loads(body) if isinstance(body, str) else body
        except json.JSONDecodeError:
            return {}
    return event


async def _run(_event: dict) -> dict:
    from hcp_intel.orchestrator import poll_due_subscriptions

    stats = await poll_due_subscriptions()
    return {
        "status": "ok",
        "job": "hcp_intel_poll",
        "processed": stats.processed,
        "items_ingested": stats.items_ingested,
        "signals_written": stats.signals_written,
        "errors": stats.errors,
    }


def handler(event: dict, context) -> dict:
    install_paths()
    configure_logging()
    return run_async(_run(_parse_event(event)))

