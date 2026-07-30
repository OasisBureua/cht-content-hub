"""wordpress_series_playlist_match — WPR-6 fuzzy-match Lambda.

One-shot Lambda (also safe to schedule) that proposes candidate
`YouTube playlist ↔ WordPress series` links for curator review.

Flow:
  1. Read every YT playlist known to ContentHub via `playlist_tags`.
     Skip any that already carry an approved link (`wp_series_slug IS NOT NULL`).
  2. Fetch the current YT title for each (reusing `fetch_playlist_title`
     from the doctor-tagger's core module).
  3. Parse doctor surnames from each title.
  4. Read every non-tombstoned `wordpress_series` row from Layer 2.
     Parse doctor surnames from each series slug.
  5. Score every (playlist, series) pair with `playlist_series_matcher_core`.
     Skip pairs where the reviewer has already decided (rejected/approved).
  6. Insert pending `playlist_series_match_review` rows for candidates
     at/above the match threshold.

Idempotent: re-invoking produces zero net writes if state hasn't changed,
because the DB's composite unique constraint (youtube_playlist_id,
wp_series_slug, status) blocks duplicate pending rows, and previously
rejected/approved pairs are excluded before scoring.

Config:
    - YOUTUBE_API_KEY (env) — required for playlist-title fetches
    - MATCH_THRESHOLD_OVERRIDE (event) — override the default 0.5
    - MAX_PLAYLISTS (event) — cap per-invocation cost, default 500
    - DRY_RUN (event) — score + report but do not insert

Invocation:
    aws lambda invoke \\
      --function-name contenthub-dev-sync-wordpress-series-playlist-match \\
      --payload '{}' \\
      /tmp/resp.json && cat /tmp/resp.json
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from shared.runtime import configure_logging, install_paths, run_async

log = logging.getLogger(__name__)

_HTTP_TIMEOUT_S = 20.0


async def _fetch_ch_playlists() -> list[dict[str, Any]]:
    """Return unlinked playlist_tags rows — [{youtube_playlist_id}, ...].

    Skips rows that already have wp_series_slug set (approved link exists)
    so we don't re-propose pairs the curator has already ruled on.
    """
    from database import async_session_maker
    from models.playlist_tag import PlaylistTag
    from sqlalchemy import select

    async with async_session_maker() as db:
        rows = (
            await db.execute(
                select(PlaylistTag.youtube_playlist_id).where(
                    PlaylistTag.wp_series_slug.is_(None)
                )
            )
        ).scalars().all()
    return [{"youtube_playlist_id": r} for r in rows]


async def _fetch_ch_series() -> list[dict[str, Any]]:
    """Return non-tombstoned wordpress_series rows — [{slug, name, surnames}]."""
    from database import async_session_maker
    from jobs.playlist_series_matcher_core import extract_surnames_from_series_slug
    from models.wordpress_projection import WordPressSeries
    from sqlalchemy import select

    async with async_session_maker() as db:
        rows = (
            await db.execute(
                select(WordPressSeries.slug, WordPressSeries.name).where(
                    WordPressSeries.deleted_at.is_(None)
                )
            )
        ).all()

    return [
        {
            "slug": slug,
            "name": name or slug,
            "surnames": extract_surnames_from_series_slug(slug),
        }
        for slug, name in rows
    ]


async def _fetch_already_decided_pairs() -> set[tuple[str, str]]:
    """Return {(playlist_id, series_slug)} for pairs already approved/rejected.

    We don't want the matcher to keep re-proposing pairs the curator has
    already ruled on — even if new pending rows would be blocked by the
    unique index, generating candidate rows to insert wastes work.
    """
    from database import async_session_maker
    from models.playlist_series_match_review import PlaylistSeriesMatchReview
    from sqlalchemy import select

    async with async_session_maker() as db:
        rows = (
            await db.execute(
                select(
                    PlaylistSeriesMatchReview.youtube_playlist_id,
                    PlaylistSeriesMatchReview.wp_series_slug,
                ).where(
                    PlaylistSeriesMatchReview.status.in_(("approved", "rejected"))
                )
            )
        ).all()
    return {(pid, slug) for pid, slug in rows}


async def _fetch_pending_pairs() -> set[tuple[str, str]]:
    """Return {(playlist_id, series_slug)} for pairs already in pending review.

    Skip these when inserting — the unique constraint would block them, and
    we avoid the wasted round-trip.
    """
    from database import async_session_maker
    from models.playlist_series_match_review import PlaylistSeriesMatchReview
    from sqlalchemy import select

    async with async_session_maker() as db:
        rows = (
            await db.execute(
                select(
                    PlaylistSeriesMatchReview.youtube_playlist_id,
                    PlaylistSeriesMatchReview.wp_series_slug,
                ).where(PlaylistSeriesMatchReview.status == "pending")
            )
        ).all()
    return {(pid, slug) for pid, slug in rows}


async def _hydrate_playlist_titles(
    playlists: list[dict[str, Any]],
    api_key: str,
) -> list[dict[str, Any]]:
    """Fetch YT titles + surnames for each playlist. Drops rows on fetch failure.

    Uses the existing fetch_playlist_title from the doctor-tagger's core
    module so behavior + typo corrections stay consistent across the two
    matcher paths.
    """
    from jobs.playlist_doctor_tagger_core import fetch_playlist_title
    from services.playlist_title_parser import extract_doctors_from_playlist_title

    hydrated: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S) as client:
        for entry in playlists:
            pid = entry["youtube_playlist_id"]
            try:
                title = await fetch_playlist_title(pid, api_key, client=client)
            except Exception as exc:
                log.warning(
                    "playlist title fetch failed",
                    extra={"playlist_id": pid, "error": str(exc)},
                )
                continue
            if not title:
                log.info("no title for playlist", extra={"playlist_id": pid})
                continue
            hydrated.append(
                {
                    "youtube_playlist_id": pid,
                    "title": title,
                    "surnames": extract_doctors_from_playlist_title(title),
                }
            )
    return hydrated


async def _insert_pending_candidates(
    candidates: list, already_pending: set[tuple[str, str]]
) -> tuple[int, int]:
    """Insert pending review rows. Returns (inserted, skipped_duplicate)."""
    from database import async_session_maker
    from models.playlist_series_match_review import PlaylistSeriesMatchReview

    inserted = 0
    skipped = 0

    async with async_session_maker() as db:
        for c in candidates:
            key = (c.youtube_playlist_id, c.wp_series_slug)
            if key in already_pending:
                skipped += 1
                continue
            db.add(
                PlaylistSeriesMatchReview(
                    youtube_playlist_id=c.youtube_playlist_id,
                    wp_series_slug=c.wp_series_slug,
                    match_score=c.score,
                    signals=c.signals(),
                    status="pending",
                )
            )
            inserted += 1
        await db.commit()

    return inserted, skipped


async def _run(event: dict[str, Any]) -> dict[str, Any]:
    from jobs.playlist_series_matcher_core import MATCH_THRESHOLD, score_all_pairs

    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    if not api_key:
        return {
            "status": "error",
            "reason": "YOUTUBE_API_KEY not configured",
        }

    threshold = float(event.get("match_threshold_override") or MATCH_THRESHOLD)
    max_playlists = int(event.get("max_playlists") or 500)
    dry_run = bool(event.get("dry_run", False))

    log.info(
        "wordpress_series_playlist_match start",
        extra={
            "threshold": threshold,
            "max_playlists": max_playlists,
            "dry_run": dry_run,
        },
    )

    playlists = (await _fetch_ch_playlists())[:max_playlists]
    log.info("candidate playlists", extra={"count": len(playlists)})

    series = await _fetch_ch_series()
    log.info("candidate series", extra={"count": len(series)})

    if not playlists or not series:
        return {
            "status": "ok",
            "job": "wordpress_series_playlist_match",
            "reason": "empty inputs",
            "playlists": len(playlists),
            "series": len(series),
        }

    playlists = await _hydrate_playlist_titles(playlists, api_key)
    log.info(
        "hydrated playlist titles",
        extra={"count": len(playlists)},
    )

    already_decided = await _fetch_already_decided_pairs()
    already_pending = await _fetch_pending_pairs()

    all_candidates = score_all_pairs(playlists, series, threshold=threshold)
    # Filter out pairs the curator already decided on.
    fresh = [
        c
        for c in all_candidates
        if (c.youtube_playlist_id, c.wp_series_slug) not in already_decided
    ]

    log.info(
        "scored candidates",
        extra={
            "above_threshold": len(all_candidates),
            "excluding_decided": len(fresh),
            "already_decided": len(already_decided),
            "already_pending": len(already_pending),
        },
    )

    if dry_run:
        return {
            "status": "ok",
            "job": "wordpress_series_playlist_match",
            "dry_run": True,
            "playlists_evaluated": len(playlists),
            "series_evaluated": len(series),
            "candidates_above_threshold": len(all_candidates),
            "fresh_candidates": len(fresh),
            "top_5": [
                {
                    "playlist_id": c.youtube_playlist_id,
                    "series_slug": c.wp_series_slug,
                    "score": round(c.score, 3),
                    "doctor_overlap": round(c.doctor_overlap, 3),
                    "title_similarity": round(c.title_similarity, 3),
                }
                for c in fresh[:5]
            ],
        }

    inserted, skipped = await _insert_pending_candidates(fresh, already_pending)

    log.info(
        "wordpress_series_playlist_match done",
        extra={
            "candidates_inserted": inserted,
            "candidates_skipped_pending": skipped,
        },
    )

    return {
        "status": "ok",
        "job": "wordpress_series_playlist_match",
        "playlists_evaluated": len(playlists),
        "series_evaluated": len(series),
        "candidates_above_threshold": len(all_candidates),
        "candidates_inserted": inserted,
        "candidates_skipped_pending": skipped,
    }


def handler(event: dict, context) -> dict:
    install_paths()
    configure_logging()
    return run_async(_run(event or {}))
