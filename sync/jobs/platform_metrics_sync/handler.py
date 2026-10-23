"""platform_metrics_sync — EventBridge Lambda handler (CPR-15).

Weekdays on dev, daily on prod. Syncs YouTube uploads and LinkedIn Ads
creatives into posts with their metrics, then relinks posts to campaigns.
Off by default (sync_jobs_enabled.platform_metrics_sync).

Event shape (all optional, for on-demand runs):
- `platforms`: list[str] — subset of ["youtube", "linkedin"]
- `dry_run`: bool — do nothing (checks the Lambda can start and reach the DB)
"""

from __future__ import annotations

from dataclasses import asdict

from shared.runtime import configure_logging, install_paths, run_async


async def _run(event: dict) -> dict:
    from database import async_session_maker
    from jobs.platform_metrics_sync_core import sync_platform_metrics

    async with async_session_maker() as db:
        stats = await sync_platform_metrics(
            db,
            platforms=event.get("platforms") or None,
            dry_run=bool(event.get("dry_run", False)),
        )

    return {
        "status": "ok" if not stats.errors else "partial",
        "job": "platform_metrics_sync",
        "error_count": len(stats.errors),
        "errors": stats.errors[:20],
        "youtube": asdict(stats.youtube) if stats.youtube else None,
        "linkedin": asdict(stats.linkedin) if stats.linkedin else None,
        "links": asdict(stats.links) if stats.links else None,
        "linkedin_token_days_left": stats.linkedin_token_days_left,
        "linkedin_token_expiring": stats.linkedin_token_expiring,
    }


def handler(event: dict, context) -> dict:
    install_paths()
    configure_logging()
    return run_async(_run(event or {}))
