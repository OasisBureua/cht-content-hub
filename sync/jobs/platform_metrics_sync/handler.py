"""platform_metrics_sync — EventBridge Lambda handler (CPR-15).

Daily. Syncs YouTube uploads into posts with today's counts, relinks posts to
campaigns, and stores one LinkedIn Ads snapshot per mapped campaign. Off by
default (sync_jobs_enabled.platform_metrics_sync).

Event shape (all optional, for on-demand runs):
- `campaign_ids`: list[int] — only these campaigns
- `platforms`: list[str] — subset of ["youtube", "linkedin"]
- `dry_run`: bool — count LinkedIn campaigns without calling the APIs or relinking
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
            campaign_ids=event.get("campaign_ids") or None,
            platforms=event.get("platforms") or None,
            dry_run=bool(event.get("dry_run", False)),
        )

    return {
        "status": "ok" if not stats.errors else "partial",
        "job": "platform_metrics_sync",
        "campaigns": stats.campaigns,
        "synced": stats.synced,
        "unmapped": stats.unmapped,
        "no_data": stats.no_data,
        "not_enabled": stats.not_enabled,
        "error_count": len(stats.errors),
        "errors": stats.errors[:20],
        "linkedin_token_days_left": stats.linkedin_token_days_left,
        "linkedin_token_expiring": stats.linkedin_token_expiring,
        "youtube": asdict(stats.youtube) if stats.youtube else None,
        "links": asdict(stats.links) if stats.links else None,
    }


def handler(event: dict, context) -> dict:
    install_paths()
    configure_logging()
    return run_async(_run(event or {}))
