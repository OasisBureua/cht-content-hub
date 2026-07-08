"""Playlist-driven doctor tagger — Content Hub producer port.

The CHM YouTube channel is the **canonical source of truth** for which
doctors participated in which shoot. The channel curator maintains one
playlist per shoot and the playlist title spells out the doctors.
Everything downstream (Shoot.doctors[], Clip.tags, Post.tags) is
derivative and must agree.

For every shoot with `youtube_playlist_id` set, this service:

1. Fetches the playlist *title* from YouTube.
2. Parses the title with `playlist_title_parser` to get canonical surnames,
   with typo corrections applied (Kree → Krie, Maklin → Makhlin,
   Cruz → Kruse, O'Shaughnessey → O'Shaughnessy) so typo variants never
   get re-emitted.
3. Updates `Shoot.doctors[]` if it disagrees with the playlist-derived list
   (audit-logged via `TagDiff(entity_type='shoot')`).
4. Pulls all video IDs in the playlist via the Data API.
5. For each Clip whose shoot_id matches, and for each linked Post on
   `chm-official`, applies the canonical doctor tag set. Non-doctor tags
   (drug:, biomarker:, conference:, topic:, etc.) are untouched.

The tagger is idempotent — re-running produces no change. Designed to run
both as a one-shot backfill and as a daily scheduled job.

## Producer-scope note

Clip and Post models are not yet on the producer (they migrate with the
video pipeline in a later epic). Until then, steps 4-6 (Clip/Post tag
propagation) are guarded — when the models aren't registered, the tagger
still updates `Shoot.doctors[]` (Shoot IS on the producer) and reports
in stats how many downstream operations were skipped. The Lambda's
cache-clear call still fires when Shoot.doctors[] changes, so CHT can
observe those updates via any endpoint that surfaces Shoot doctors.
When Clip/Post land on the producer, the guarded blocks activate
without code changes.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.shoot import Shoot
from services.doctor_tag_corrections import DOCTOR_TAG_CORRECTIONS
from services.playlist_title_parser import (
    doctor_tags_from_playlist_title,
    extract_doctors_from_playlist_title,
)

logger = logging.getLogger(__name__)

_YT_PLAYLIST_ITEMS_URL = "https://www.googleapis.com/youtube/v3/playlistItems"
_YT_PLAYLISTS_URL = "https://www.googleapis.com/youtube/v3/playlists"

_TITLE_PREFIXES_RE = re.compile(r"^\s*Drs?\.\s+", re.IGNORECASE)


# ─────────────────────────────────────────────────────────────────────────────
# Optional Clip/Post model detection (producer-scope graceful degradation)
# ─────────────────────────────────────────────────────────────────────────────


def _load_clip_post_models():
    """Return (Clip, Post) if both are registered on the producer, else (None, None).

    Clip and Post migrate with the video pipeline in a later epic. Until then,
    the tagger runs Shoot-only and skips the propagation steps. This function
    isolates the import so the tagger module itself imports cleanly.
    """
    try:
        from models.clip import Clip  # type: ignore
        from models.post import Post  # type: ignore
        return Clip, Post
    except ImportError:
        return None, None


# ─────────────────────────────────────────────────────────────────────────────
# YouTube playlist fetch
# ─────────────────────────────────────────────────────────────────────────────


async def fetch_playlist_title(
    playlist_id: str,
    api_key: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[str]:
    """Return the YouTube-side title of a playlist, or None if not found."""
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=15.0)
    try:
        r = await client.get(
            _YT_PLAYLISTS_URL,
            params={"part": "snippet", "id": playlist_id, "key": api_key},
        )
        r.raise_for_status()
        data = r.json()
        items = data.get("items") or []
        if not items:
            return None
        return items[0].get("snippet", {}).get("title")
    finally:
        if owns_client:
            await client.aclose()


async def fetch_playlist_video_ids(
    playlist_id: str,
    api_key: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> list[str]:
    """Return every video ID in a YouTube playlist (paginated)."""
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=15.0)
    try:
        video_ids: list[str] = []
        page_token: Optional[str] = None
        while True:
            params = {
                "part": "contentDetails",
                "playlistId": playlist_id,
                "maxResults": 50,
                "key": api_key,
            }
            if page_token:
                params["pageToken"] = page_token
            r = await client.get(_YT_PLAYLIST_ITEMS_URL, params=params)
            r.raise_for_status()
            data = r.json()
            for item in data.get("items", []):
                vid = item.get("contentDetails", {}).get("videoId")
                if vid:
                    video_ids.append(vid)
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return video_ids
    finally:
        if owns_client:
            await client.aclose()


# ─────────────────────────────────────────────────────────────────────────────
# Tag-application logic (pure-ish, no I/O — easy to unit-test)
# ─────────────────────────────────────────────────────────────────────────────


def _strip_doctor_tags(tags: Optional[list[str]]) -> list[str]:
    """Return `tags` with any `doctor:*` entries removed. Preserves order."""
    if not tags:
        return []
    return [t for t in tags if not t.startswith("doctor:")]


def merge_doctor_tags(
    existing: Optional[list[str]], canonical_doctor_tags: list[str]
) -> list[str]:
    """Return `existing` with all `doctor:*` tags replaced by the canonical set.

    Non-doctor tags are preserved in their original order. Doctor tags are
    appended (in canonical input order) at the end. De-duped overall.

    Short-circuit: if `existing` already has exactly the canonical doctor
    set (set-equal, ignoring positional order), return `existing` unchanged.

    This is the AUTHORITATIVE merge used by one-shot backfills — it strips
    pre-existing typos and any wrong doctors. For the daily cron, prefer
    `union_doctor_tags` so we never remove user-curated tags.
    """
    existing_list = list(existing or [])
    existing_doctors = {t for t in existing_list if t.startswith("doctor:")}
    if existing_doctors == set(canonical_doctor_tags):
        return existing_list

    non_doctor = _strip_doctor_tags(existing_list)
    seen: set[str] = set()
    out: list[str] = []
    for t in non_doctor:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    for t in canonical_doctor_tags:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def union_doctor_tags(
    existing: Optional[list[str]], canonical_doctor_tags: list[str]
) -> list[str]:
    """Additive-only merge: ensure every tag in `canonical_doctor_tags` is
    present in `existing`, but never remove an existing `doctor:*` tag.

    Used by the daily cron so hand-edits in the (future) tag-editor UI are
    preserved. The backfill script uses `merge_doctor_tags` for the one-time
    aggressive cleanup; everything routine after that uses this helper.
    """
    existing_list = list(existing or [])
    existing_set = set(existing_list)
    missing = [t for t in canonical_doctor_tags if t not in existing_set]
    if not missing:
        return existing_list
    return existing_list + missing


def _canonical_doctors_field(surnames: list[str]) -> list[str]:
    """Render canonical surnames as Shoot.doctors[] entries.

    Shoot.doctors stores entries like 'Dr. O'Shaughnessy' / 'Dr. Pegram'.
    """
    return [f"Dr. {s}" for s in surnames]


def _surname_from_doctor_field(doctor: str) -> Optional[str]:
    """Extract the canonical surname suffix from a Shoot.doctors[] entry."""
    if not doctor:
        return None
    cleaned = _TITLE_PREFIXES_RE.sub("", doctor.strip())
    tokens = cleaned.split()
    if not tokens:
        return None
    surname = tokens[-1].strip().rstrip(".,;")
    if not surname:
        return None
    return DOCTOR_TAG_CORRECTIONS.get(surname, surname)


def _shoot_doctors_disagree(
    current: Optional[list[str]], parsed_surnames: list[str]
) -> bool:
    """Return True if shoot.doctors[] doesn't already reflect parsed_surnames.

    Compares on canonical surname only — the prefix ('Dr. ' vs no prefix)
    and exact capitalization of the parser output are tolerated as long as
    the surname set matches.
    """
    if not parsed_surnames:
        return False  # never overwrite with empty
    current_surnames = set()
    for doc in current or []:
        s = _surname_from_doctor_field(doc)
        if s:
            current_surnames.add(s)
    return current_surnames != set(parsed_surnames)


# ─────────────────────────────────────────────────────────────────────────────
# Diff + stats types
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class TagDiff:
    entity_type: str  # 'clip' | 'post' | 'shoot'
    entity_id: str
    provider_post_id: Optional[str]
    title: Optional[str]
    before: list[str]
    after: list[str]
    shoot_id: str
    shoot_name: str

    @property
    def changed(self) -> bool:
        return self.before != self.after


@dataclass
class TagRunStats:
    shoots_processed: int = 0
    shoots_with_no_playlist: int = 0
    shoots_doctors_corrected: int = 0
    clips_touched: int = 0
    clips_changed: int = 0
    posts_touched: int = 0
    posts_changed: int = 0
    playlist_videos_not_in_producer: list[str] = field(default_factory=list)
    playlists_title_fetch_failed: list[str] = field(default_factory=list)
    playlists_orphaned_404: list[str] = field(default_factory=list)
    playlists_unparseable: list[str] = field(default_factory=list)
    api_errors: list[str] = field(default_factory=list)
    clip_post_skipped_models_missing: bool = False

    def summary(self) -> str:
        return (
            f"shoots_processed={self.shoots_processed} "
            f"shoots_no_playlist={self.shoots_with_no_playlist} "
            f"shoots_doctors_corrected={self.shoots_doctors_corrected} "
            f"clips_touched={self.clips_touched} clips_changed={self.clips_changed} "
            f"posts_touched={self.posts_touched} posts_changed={self.posts_changed} "
            f"orphaned_404={len(self.playlists_orphaned_404)} "
            f"title_fetch_failed={len(self.playlists_title_fetch_failed)} "
            f"unparseable={len(self.playlists_unparseable)} "
            f"api_errors={len(self.api_errors)} "
            f"clip_post_skipped={self.clip_post_skipped_models_missing}"
        )

    def as_dict(self) -> dict:
        return {
            "shoots_processed": self.shoots_processed,
            "shoots_doctors_corrected": self.shoots_doctors_corrected,
            "clips_changed": self.clips_changed,
            "posts_changed": self.posts_changed,
            "orphaned_404_count": len(self.playlists_orphaned_404),
            "api_error_count": len(self.api_errors),
            "clip_post_skipped_models_missing": self.clip_post_skipped_models_missing,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Main entrypoint
# ─────────────────────────────────────────────────────────────────────────────


async def tag_clips_from_playlists(
    db: AsyncSession,
    *,
    dry_run: bool = False,
    mode: str = "replace",
) -> tuple[TagRunStats, list[TagDiff]]:
    """Walk every shoot with a youtube_playlist_id; derive canonical doctors
    from the playlist title; apply to Shoot.doctors[] and (when models are
    present) every chm-official Clip + linked Post.

    Returns `(stats, diffs)`. When `dry_run=True` no DB writes happen; diffs
    still reflect what would have changed.

    `mode='replace'` (default, used by backfill): canonical doctor set
    REPLACES whatever doctor tags exist (strips typos + wrong doctors).
    `mode='union'` (used by daily cron): canonical doctor set is UNIONED
    with existing doctor tags — never removes hand-curated tags.
    """
    if mode not in ("replace", "union"):
        raise ValueError(f"mode must be 'replace' or 'union', got {mode!r}")
    merge_fn = merge_doctor_tags if mode == "replace" else union_doctor_tags

    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    if not api_key:
        raise RuntimeError("YOUTUBE_API_KEY not configured")

    Clip, Post = _load_clip_post_models()
    clip_post_active = Clip is not None and Post is not None

    stats = TagRunStats()
    stats.clip_post_skipped_models_missing = not clip_post_active
    diffs: list[TagDiff] = []

    if not clip_post_active:
        logger.info(
            "Clip/Post models not registered on producer — running "
            "Shoot-only. Steps 5-6 (clip + post tag propagation) will "
            "activate when the video pipeline migrates."
        )

    shoots_res = await db.execute(
        select(Shoot).where(Shoot.youtube_playlist_id.is_not(None))
    )
    shoots = list(shoots_res.scalars())

    if not shoots:
        logger.info("No shoots with youtube_playlist_id set — nothing to do.")
        return stats, diffs

    async with httpx.AsyncClient(timeout=15.0) as client:
        for shoot in shoots:
            stats.shoots_processed += 1
            if not shoot.youtube_playlist_id:
                stats.shoots_with_no_playlist += 1
                continue

            # Step 1: fetch the playlist title from YouTube (canonical source).
            try:
                playlist_title = await fetch_playlist_title(
                    shoot.youtube_playlist_id, api_key, client=client
                )
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    # Orphaned playlist — audit confirmed 16 of 26 prod
                    # playlists are 404s. Legacy behavior: skip + log.
                    stats.playlists_orphaned_404.append(shoot.youtube_playlist_id)
                    logger.info(
                        "Playlist %s for shoot %s returned 404 (orphaned) — "
                        "skipping",
                        shoot.youtube_playlist_id, shoot.id,
                    )
                    continue
                stats.api_errors.append(
                    f"playlist_title playlist={shoot.youtube_playlist_id} "
                    f"shoot={shoot.id} err={e!r}"
                )
                logger.error(
                    "YouTube API error fetching title for playlist %s: %r",
                    shoot.youtube_playlist_id, e,
                )
                continue
            except httpx.HTTPError as e:
                stats.api_errors.append(
                    f"playlist_title playlist={shoot.youtube_playlist_id} "
                    f"shoot={shoot.id} err={e!r}"
                )
                logger.error(
                    "YouTube network error fetching title for playlist %s: %r",
                    shoot.youtube_playlist_id, e,
                )
                continue

            if not playlist_title:
                stats.playlists_title_fetch_failed.append(shoot.youtube_playlist_id)
                logger.warning(
                    "Playlist %s for shoot %s returned no title",
                    shoot.youtube_playlist_id, shoot.id,
                )
                continue

            # Step 2: parse canonical doctors from the playlist title.
            parsed_surnames = extract_doctors_from_playlist_title(playlist_title)
            canonical_tags = sorted(doctor_tags_from_playlist_title(playlist_title))
            if not canonical_tags:
                stats.playlists_unparseable.append(
                    f"{shoot.youtube_playlist_id}: {playlist_title!r}"
                )
                logger.warning(
                    "Could not parse doctors from playlist title %r "
                    "(playlist=%s, shoot=%s)",
                    playlist_title, shoot.youtube_playlist_id, shoot.id,
                )
                continue

            # Step 3: correct Shoot.doctors[] if it disagrees.
            if _shoot_doctors_disagree(shoot.doctors, parsed_surnames):
                before_doctors = list(shoot.doctors or [])
                after_doctors = _canonical_doctors_field(parsed_surnames)
                diffs.append(
                    TagDiff(
                        entity_type="shoot",
                        entity_id=str(shoot.id),
                        provider_post_id=shoot.youtube_playlist_id,
                        title=playlist_title,
                        before=before_doctors,
                        after=after_doctors,
                        shoot_id=str(shoot.id),
                        shoot_name=shoot.name or "",
                    )
                )
                stats.shoots_doctors_corrected += 1
                if not dry_run:
                    shoot.doctors = after_doctors

            # Steps 4-6 (Clip + Post propagation) require Clip and Post
            # models to be registered on the producer. If they aren't, skip
            # the rest of this shoot's processing and let the next iteration
            # handle Shoot-only updates for the next shoot.
            if not clip_post_active:
                continue

            # Step 4: fetch playlist video IDs.
            try:
                video_ids = await fetch_playlist_video_ids(
                    shoot.youtube_playlist_id, api_key, client=client
                )
            except httpx.HTTPError as e:
                stats.api_errors.append(
                    f"playlist_items playlist={shoot.youtube_playlist_id} "
                    f"shoot={shoot.id} err={e!r}"
                )
                logger.error(
                    "YouTube API error for playlist items %s: %r",
                    shoot.youtube_playlist_id, e,
                )
                continue

            if not video_ids:
                logger.info(
                    "Playlist %s for shoot %s is empty (no items)",
                    shoot.youtube_playlist_id, shoot.id,
                )
                continue

            # Step 5: rewrite tags on every Clip belonging to this shoot.
            clips_res = await db.execute(
                select(Clip).where(Clip.shoot_id == shoot.id)  # type: ignore
            )
            clips = list(clips_res.scalars())

            # Self-heal: realign any Post.shoot_id that drifted from its
            # linked Clip.shoot_id. Preserves the legacy behavior — operator
            # clip reassignments without post updates would otherwise leave
            # posts pointing at the old shoot indefinitely.
            clip_ids_here = {c.id for c in clips}
            if clip_ids_here:
                drifted_posts = list(
                    (await db.execute(
                        select(Post).where(  # type: ignore
                            Post.clip_id.in_(clip_ids_here),  # type: ignore
                            Post.shoot_id != shoot.id,  # type: ignore
                        )
                    )).scalars()
                )
                for p in drifted_posts:
                    if not dry_run:
                        p.shoot_id = shoot.id
                    logger.info(
                        "self-heal: realigned post=%s clip=%s shoot %s -> %s",
                        p.id, p.clip_id, p.shoot_id, shoot.id,
                    )
            for clip in clips:
                stats.clips_touched += 1
                before = list(clip.tags or [])
                after = merge_fn(before, canonical_tags)
                diff = TagDiff(
                    entity_type="clip",
                    entity_id=clip.id,
                    provider_post_id=None,
                    title=clip.title,
                    before=before,
                    after=after,
                    shoot_id=str(shoot.id),
                    shoot_name=shoot.name or "",
                )
                if diff.changed:
                    diffs.append(diff)
                    stats.clips_changed += 1
                    if not dry_run:
                        clip.tags = after

            # Step 6: rewrite tags on Posts belonging to this shoot.
            posts_res = await db.execute(
                select(Post).where(  # type: ignore
                    Post.channel == "chm-official",  # type: ignore
                    (Post.provider_post_id.in_(video_ids)) | (Post.shoot_id == shoot.id),  # type: ignore
                )
            )
            all_candidate_posts = list(posts_res.scalars())
            posts: list = []
            for p in all_candidate_posts:
                in_playlist = p.provider_post_id in video_ids
                belongs_to_shoot = p.shoot_id == shoot.id
                post_has_no_shoot = p.shoot_id is None
                if in_playlist and belongs_to_shoot:
                    posts.append(p)
                elif belongs_to_shoot and not in_playlist:
                    posts.append(p)
                elif in_playlist and post_has_no_shoot:
                    posts.append(p)
                # else: in_playlist but filed under different shoot — skip

            found_vid_ids = {p.provider_post_id for p in all_candidate_posts}
            missing = [v for v in video_ids if v not in found_vid_ids]
            stats.playlist_videos_not_in_producer.extend(missing)

            for post in posts:
                stats.posts_touched += 1
                before = list(post.tags or [])
                after = merge_fn(before, canonical_tags)
                diff = TagDiff(
                    entity_type="post",
                    entity_id=post.id,
                    provider_post_id=post.provider_post_id,
                    title=post.title,
                    before=before,
                    after=after,
                    shoot_id=str(shoot.id),
                    shoot_name=shoot.name or "",
                )
                if diff.changed:
                    diffs.append(diff)
                    stats.posts_changed += 1
                    if not dry_run:
                        post.tags = after

    if not dry_run:
        await db.commit()

    logger.info("Playlist doctor-tagging run: %s", stats.summary())
    return stats, diffs


def _doctor_only(tags: Iterable[str]) -> list[str]:
    return sorted(t for t in tags if t.startswith("doctor:"))
