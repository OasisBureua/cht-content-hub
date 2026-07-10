"""playlist_doctor_tagger — EventBridge Lambda handler.

Daily 04:30 UTC cron. Reads YouTube playlist titles for every Shoot with
`youtube_playlist_id` set and propagates canonical `doctor:*` tags to
Shoot.doctors[] and (when the models are on the producer) linked Clips
and Posts.

Event shape:
- `mode`: "union" (default, daily cron) or "replace" (backfill)
- `dry_run`: bool (default False)

Reserved concurrency = 1 (tag writes are not safe under concurrent runs).
"""

from __future__ import annotations

from shared.runtime import configure_logging, install_paths, run_async


async def _run(event: dict) -> dict:
    from database import async_session_maker
    from jobs.playlist_doctor_tagger import tag_clips_from_playlists

    mode = event.get("mode", "union")
    dry_run = bool(event.get("dry_run", False))

    async with async_session_maker() as db:
        stats, _diffs = await tag_clips_from_playlists(
            db, dry_run=dry_run, mode=mode
        )

    # Invalidate CHT catalog cache after successful writes that affect
    # doctor tagging (Shoot.doctors changes surface through KOL/shoot
    # queries CHT proxies).
    if not dry_run and (
        stats.shoots_doctors_corrected > 0
        or stats.clips_changed > 0
        or stats.posts_changed > 0
    ):
        from shared.cht_cache import clear_cht_catalog_cache
        clear_cht_catalog_cache(job="playlist_doctor_tagger")

    return {"status": "ok", "job": "playlist_doctor_tagger", **stats.as_dict()}


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
