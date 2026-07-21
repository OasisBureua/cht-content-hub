"""YouTube snippet.tags → Clip.tags propagation.

Editorial teams tag videos on YouTube Studio (snippet.tags). This job
pulls those tags per video every 12h and merges them into Clip.tags
under the `yt:` namespace so downstream consumers (public /clips API,
CHT catalog) can filter/browse by them.

## Design

- Batch fetch `youtube.videos.list?part=snippet` (50 IDs per call, YT
  API limit). One YT unit per call.
- Match by `Clip.id`'s trailing YouTube video ID segment
  (`official:youtube:<videoId>`), platform=youtube, channel=chm-official.
- Update Clip.tags: strip all existing `yt:*`, add the fresh `yt:<value>`
  for each snippet.tags entry, keep every other namespace untouched.
- Respect `tags_curator_override` — if True, skip the row (curator lock
  from SCRUM-75).

## Idempotence

Re-running with unchanged YT tags produces zero diffs. The stats
(`yt_tags_added` etc.) reflect actual mutations.

## Failure modes

- Video ID doesn't exist on YouTube (deleted) — YT API omits it from
  response, we do nothing; existing yt:* tags stay (would need a
  separate cleanup job to purge). Recorded in stats.
- YouTube quota exhausted — surfaced as an exception; Lambda retries
  via SQS DLQ (post_tagging uses schedule, not SQS — so this raises
  and CloudWatch alarm fires).
- YOUTUBE_API_KEY not set — RuntimeError like playlist_doctor_tagger.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.clip import Clip

logger = logging.getLogger(__name__)

_YT_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
_YT_MAX_IDS_PER_CALL = 50  # YouTube Data API v3 hard limit for videos.list
_YT_NAMESPACE = "yt"


@dataclass
class PostTaggingStats:
    clips_processed: int = 0
    clips_with_yt_id: int = 0
    clips_curator_locked_skipped: int = 0
    clips_missing_from_yt: int = 0
    clips_changed: int = 0
    yt_tags_added: int = 0
    yt_tags_removed: int = 0
    api_errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"clips_processed={self.clips_processed} "
            f"with_yt_id={self.clips_with_yt_id} "
            f"curator_locked={self.clips_curator_locked_skipped} "
            f"missing_from_yt={self.clips_missing_from_yt} "
            f"changed={self.clips_changed} "
            f"yt_added={self.yt_tags_added} yt_removed={self.yt_tags_removed} "
            f"api_errors={len(self.api_errors)}"
        )


def _clip_youtube_id(clip: Clip) -> Optional[str]:
    """Extract the trailing YouTube video ID from `Clip.id`.

    Shape: `official:youtube:<video_id>`. Returns None for anything else.
    """
    if clip.platform != "youtube":
        return None
    parts = (clip.id or "").split(":")
    if len(parts) < 3 or not parts[-1]:
        return None
    return parts[-1]


def _strip_yt_tags(tags: Optional[list[str]]) -> list[str]:
    """Return `tags` with any `yt:*` entries removed. Preserves order."""
    if not tags:
        return []
    prefix = f"{_YT_NAMESPACE}:"
    return [t for t in tags if not (isinstance(t, str) and t.startswith(prefix))]


def merge_yt_tags(
    existing: Optional[list[str]], canonical_yt_tags: list[str]
) -> list[str]:
    """Replace the `yt:*` slice of `existing` with `canonical_yt_tags`.

    Non-yt tags preserved in original order. yt tags appended in the
    order YouTube returned them (respecting curator arrangement on YT).
    De-duped overall. Idempotent — if `existing`'s yt slice equals the
    canonical set, returns existing unchanged.
    """
    existing_list = list(existing or [])
    existing_yt = {
        t for t in existing_list
        if isinstance(t, str) and t.startswith(f"{_YT_NAMESPACE}:")
    }
    if existing_yt == set(canonical_yt_tags):
        return existing_list

    non_yt = _strip_yt_tags(existing_list)
    seen: set[str] = set()
    out: list[str] = []
    for t in non_yt:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    for t in canonical_yt_tags:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


async def fetch_snippet_tags(
    video_ids: list[str],
    api_key: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, list[str]]:
    """Return `{video_id: [snippet.tag, ...]}` for the given IDs.

    Batched by YT's 50-per-call limit. Missing IDs (deleted videos) are
    absent from the returned dict — caller decides what to do.

    Uses only the `snippet` part (1 quota unit per call). Empty tag lists
    are included as `video_id: []` when the video exists but has no tags.
    """
    if not video_ids:
        return {}
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=15.0)
    try:
        results: dict[str, list[str]] = {}
        for offset in range(0, len(video_ids), _YT_MAX_IDS_PER_CALL):
            chunk = video_ids[offset : offset + _YT_MAX_IDS_PER_CALL]
            r = await client.get(
                _YT_VIDEOS_URL,
                params={
                    "part": "snippet",
                    "id": ",".join(chunk),
                    "key": api_key,
                    "maxResults": _YT_MAX_IDS_PER_CALL,
                },
            )
            r.raise_for_status()
            data = r.json()
            for item in data.get("items", []):
                vid = item.get("id")
                snippet = item.get("snippet") or {}
                tags = snippet.get("tags") or []
                if isinstance(vid, str) and vid:
                    results[vid] = [t for t in tags if isinstance(t, str)]
        return results
    finally:
        if owns_client:
            await client.aclose()


async def tag_clips_from_youtube(
    db: AsyncSession,
    *,
    dry_run: bool = False,
    fetch: Optional[
        object
    ] = None,  # Optional injection point for tests (see e2e test).
) -> PostTaggingStats:
    """Refresh `yt:*` tags on every chm-official YouTube clip.

    Idempotent, safe to re-run. Curator-locked clips are skipped.

    Args:
      dry_run: report only; no DB writes.
      fetch: optional coroutine `(ids, api_key) -> dict[id, tags]` for
        testing; defaults to `fetch_snippet_tags`.

    Returns run stats. Caller commits (matches playlist_doctor_tagger
    ergonomics).
    """
    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    if not api_key:
        raise RuntimeError("YOUTUBE_API_KEY not configured")

    fetch_fn = fetch or fetch_snippet_tags

    stats = PostTaggingStats()

    clips = list(
        (
            await db.execute(
                select(Clip).where(
                    Clip.channel == "chm-official",
                    Clip.platform == "youtube",
                )
            )
        ).scalars()
    )
    stats.clips_processed = len(clips)

    # Build a video_id → [Clip] map. In practice each video has one clip,
    # but the code tolerates duplicates.
    by_yt_id: dict[str, list[Clip]] = {}
    for clip in clips:
        vid = _clip_youtube_id(clip)
        if not vid:
            continue
        stats.clips_with_yt_id += 1
        by_yt_id.setdefault(vid, []).append(clip)

    if not by_yt_id:
        logger.info("post_tagging: no chm-official youtube clips — nothing to do.")
        return stats

    try:
        snippet_tags_by_id = await fetch_fn(sorted(by_yt_id.keys()), api_key)
    except httpx.HTTPError as e:
        stats.api_errors.append(f"videos.list err={e!r}")
        logger.error("post_tagging: YouTube API error: %r", e)
        return stats

    for vid, clip_list in by_yt_id.items():
        yt_tags = snippet_tags_by_id.get(vid)

        # Compute canonical yt:* set (empty list means "video exists on YT
        # but has no tags" — we still strip stale yt:*). None means video
        # missing from YT entirely — we leave the clip alone entirely
        # after accounting for it in stats + still checking curator lock
        # so callers get accurate lock stats.
        video_missing_from_yt = yt_tags is None
        canonical: list[str] = []
        if not video_missing_from_yt:
            seen_lower: set[str] = set()
            for t in yt_tags:
                stripped = t.strip()
                if not stripped:
                    continue
                key = stripped.lower()
                if key in seen_lower:
                    continue
                seen_lower.add(key)
                canonical.append(f"{_YT_NAMESPACE}:{stripped}")

        for clip in clip_list:
            # Check curator lock first so lock-stat is accurate regardless
            # of YT fetch outcome. Curator-locked clips are never touched
            # by this job.
            if getattr(clip, "tags_curator_override", False):
                stats.clips_curator_locked_skipped += 1
                continue

            if video_missing_from_yt:
                stats.clips_missing_from_yt += 1
                continue

            before = list(clip.tags or [])
            after = merge_yt_tags(before, canonical)
            if before == after:
                continue

            stats.clips_changed += 1
            before_yt = {
                t for t in before
                if isinstance(t, str) and t.startswith(f"{_YT_NAMESPACE}:")
            }
            after_yt = set(canonical)
            stats.yt_tags_added += len(after_yt - before_yt)
            stats.yt_tags_removed += len(before_yt - after_yt)

            if not dry_run:
                clip.tags = after

    if not dry_run:
        await db.commit()

    logger.info("post_tagging run: %s", stats.summary())
    return stats
