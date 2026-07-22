"""Tag backfill + reconcile job (SCRUM-76).

Complements the daily playlist_doctor_tagger. Two responsibilities the
tagger alone doesn't cover:

1. **Prune dead YouTube playlist IDs.** The 2026-07 audit found ~16/27
   playlists returning 404 from the Data API (orphaned/deleted). The
   tagger currently logs and skips these on every run. This job flips
   Shoot.youtube_playlist_id -> NULL for confirmed-dead playlists so
   the tagger stops rechecking them daily (still recoverable — a curator
   can re-attach a new playlist ID).

2. **Report untagged clips.** Clips whose `tags` are empty (or only
   contain non-doctor tags after the tagger runs) — surfaced as a list
   the curator UI can render as a "needs attention" bucket.

Returns a ReconcileReport dataclass that the caller (Lambda handler or
one-shot script) can log to CloudWatch and/or POST to Slack.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jobs.playlist_doctor_tagger import TagRunStats, tag_clips_from_playlists
from models.clip import Clip
from models.shoot import Shoot

logger = logging.getLogger(__name__)


@dataclass
class ReconcileReport:
    tagger_stats: TagRunStats
    pruned_shoot_ids: list[str] = field(default_factory=list)
    untagged_clip_ids: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"reconcile_pruned={len(self.pruned_shoot_ids)} "
            f"reconcile_untagged={len(self.untagged_clip_ids)} "
            f"tagger[{self.tagger_stats.summary()}]"
        )


async def _prune_dead_playlists(
    db: AsyncSession, dead_playlist_ids: list[str], *, dry_run: bool
) -> list[str]:
    """Set Shoot.youtube_playlist_id = NULL for shoots whose playlist 404'd.

    Returns the shoot IDs that were pruned. Curator can re-attach a new
    playlist ID via a follow-up admin write.
    """
    if not dead_playlist_ids:
        return []
    shoots = list(
        (
            await db.execute(
                select(Shoot).where(
                    Shoot.youtube_playlist_id.in_(dead_playlist_ids)
                )
            )
        ).scalars()
    )
    pruned: list[str] = []
    for shoot in shoots:
        if not dry_run:
            shoot.youtube_playlist_id = None
        pruned.append(shoot.id)
        logger.info(
            "reconcile: pruned dead playlist_id from shoot %s (was %s)",
            shoot.id, shoot.youtube_playlist_id,
        )
    return pruned


async def _find_untagged_clips(db: AsyncSession) -> list[str]:
    """Clips on chm-official with empty tags OR no doctor tags."""
    clips = list(
        (
            await db.execute(
                select(Clip).where(Clip.channel == "chm-official")
            )
        ).scalars()
    )
    untagged: list[str] = []
    for clip in clips:
        tags = clip.tags or []
        has_doctor = any(t.startswith("doctor:") for t in tags)
        if not has_doctor:
            untagged.append(clip.id)
    return untagged


async def reconcile_tags(
    db: AsyncSession,
    *,
    dry_run: bool = False,
    prune_dead_playlists: bool = True,
) -> ReconcileReport:
    """Run the tagger + prune dead playlists + report untagged clips.

    Args:
      dry_run: if True, no DB writes happen. Report still populated.
      prune_dead_playlists: if False, log dead playlist IDs but don't
        NULL them out — useful for a first-run audit report.
    """
    tagger_stats, _diffs = await tag_clips_from_playlists(db, dry_run=dry_run)

    pruned: list[str] = []
    if prune_dead_playlists and tagger_stats.playlists_orphaned_404:
        pruned = await _prune_dead_playlists(
            db, tagger_stats.playlists_orphaned_404, dry_run=dry_run
        )

    untagged = await _find_untagged_clips(db)

    if not dry_run:
        await db.commit()

    report = ReconcileReport(
        tagger_stats=tagger_stats,
        pruned_shoot_ids=pruned,
        untagged_clip_ids=untagged,
    )
    logger.info("Tag reconcile: %s", report.summary())
    return report
