"""post_tagging — EventBridge Lambda handler.

12-hour cron. Refreshes `yt:*` tags on every chm-official YouTube clip
from the video's `snippet.tags` on YouTube. Editorial teams tag videos
on YouTube Studio; this job pulls that into Clip.tags so the public
tag surface reflects it.

Event shape:
- `dry_run`: bool (default False) — report only, no DB writes

Reserved concurrency = 1 (writes to Clip.tags are not safe under
concurrent runs).

Fires cache_clear on any change so CHT's Redis catalog invalidates.
"""

from __future__ import annotations

from shared.runtime import configure_logging, install_paths, run_async


async def _run(event: dict) -> dict:
    from database import async_session_maker
    from jobs.post_tagging import tag_clips_from_youtube

    dry_run = bool(event.get("dry_run", False))

    async with async_session_maker() as db:
        stats = await tag_clips_from_youtube(db, dry_run=dry_run)

    if not dry_run and stats.clips_changed > 0:
        from shared.cht_cache import clear_cht_catalog_cache

        clear_cht_catalog_cache(job="post_tagging")

    return {
        "status": "ok",
        "job": "post_tagging",
        "dry_run": dry_run,
        "clips_processed": stats.clips_processed,
        "clips_changed": stats.clips_changed,
        "yt_tags_added": stats.yt_tags_added,
        "yt_tags_removed": stats.yt_tags_removed,
        "curator_locked_skipped": stats.clips_curator_locked_skipped,
        "missing_from_yt": stats.clips_missing_from_yt,
        "api_error_count": len(stats.api_errors),
    }


def handler(event: dict, context) -> dict:
    install_paths()
    configure_logging()
    return run_async(_run(event or {}))
