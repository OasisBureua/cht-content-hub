"""CPR-56: parse HubSpot social payloads from ``campaign.hubspot_raw_data``.

Platform sync stores SOCIAL_BROADCAST (and optional normalized ``socialPosts``)
on the campaign. This module turns that JSON into typed rows and upserts
``posts`` / ``post_metrics_daily`` (links in a later chunk).

No HubSpot HTTP — snapshot only.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.campaign import Campaign
from models.post import Post
from models.social import (
    BASIS_LIFETIME,
    LINK_ACTIVE,
    LINK_HUBSPOT_CAMPAIGN,
    LINK_MANUAL,
    LINK_REMOVED,
    PostCampaignLink,
    PostMetricDaily,
)
from services import post_links

POST_SOURCE_HUBSPOT = "hubspot"
METRICS_SOURCE_HUBSPOT = "hubspot"
METRICS_BASIS_HUBSPOT = BASIS_LIFETIME

log = logging.getLogger(__name__)

# posts.platform slugs (free string; not Campaign Platform enum).
PLATFORM_LINKEDIN = "linkedin"
PLATFORM_FACEBOOK = "facebook"
PLATFORM_INSTAGRAM = "instagram"
PLATFORM_X = "x"
PLATFORM_HUBSPOT = "hubspot"


@dataclass(frozen=True)
class HubSpotSocialPostRow:
    """One SOCIAL_BROADCAST asset ready for Hub upsert."""

    provider_post_id: str
    platform: str
    title: str
    facebook_clicks: int
    linkedin_clicks: int
    twitter_clicks: int
    total_clicks: int
    content_url: str | None = None
    posted_at: datetime | None = None
    channel_key: str | None = None
    network_label: str | None = None


@dataclass(frozen=True)
class HubSpotSocialSnapshot:
    """Parsed HubSpot analytics blob for one Hub campaign."""

    hubspot_campaign_id: str
    reporting_period_start: date | None
    reporting_period_end: date | None
    posts: tuple[HubSpotSocialPostRow, ...]


def _as_record(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _as_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value == value:  # not NaN
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(float(value.strip()))
        except ValueError:
            return 0
    return 0


def _parse_iso_date(value: Any) -> date | None:
    raw = _as_str(value)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _parse_iso_datetime(value: Any) -> datetime | None:
    raw = _as_str(value)
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def platform_from_network(network: str | None, channel_key: str | None = None) -> str:
    """Map Platform/HubSpot network labels to ``posts.platform`` slugs."""
    for text in (network, channel_key):
        if not text:
            continue
        lower = text.lower()
        if lower.startswith("linkedin") or "linkedin" in lower:
            return PLATFORM_LINKEDIN
        if lower.startswith("instagram") or "instagram" in lower:
            return PLATFORM_INSTAGRAM
        if lower.startswith("facebook") or "facebook" in lower:
            return PLATFORM_FACEBOOK
        if (
            lower.startswith("twitter")
            or lower.startswith("x-")
            or lower == "x"
            or "twitter" in lower
        ):
            return PLATFORM_X
    return PLATFORM_HUBSPOT


def _metric_click(metrics: dict[str, Any], *keys: str) -> int:
    for key in keys:
        if key in metrics and metrics[key] is not None:
            return _as_int(metrics[key])
    return 0


def _clicks_from_asset_metrics(metrics: dict[str, Any]) -> tuple[int, int, int]:
    return (
        _metric_click(metrics, "FACEBOOK_CLICKS", "facebookClicks"),
        _metric_click(metrics, "LINKEDIN_CLICKS", "linkedinClicks"),
        _metric_click(metrics, "TWITTER_CLICKS", "twitterClicks"),
    )


def _infer_network_from_asset(name: str, metrics: dict[str, Any]) -> str | None:
    lower = name.lower()
    if "linkedin" in lower:
        return "LinkedIn"
    if "instagram" in lower:
        return "Instagram"
    if "facebook" in lower:
        return "Facebook"
    if "twitter" in lower or " x " in f" {lower} ":
        return "X"
    fb, li, tw = _clicks_from_asset_metrics(metrics)
    if li > 0:
        return "LinkedIn"
    if fb > 0:
        return "Facebook"
    if tw > 0:
        return "X"
    return None


def _row_from_normalized_social_post(entry: dict[str, Any]) -> HubSpotSocialPostRow | None:
    """Platform ``socialPosts[]`` shape (camelCase)."""
    post_id = _as_str(entry.get("id"))
    if not post_id:
        return None
    fb = _as_int(entry.get("facebookClicks"))
    li = _as_int(entry.get("linkedinClicks"))
    tw = _as_int(entry.get("twitterClicks"))
    total = _as_int(entry.get("totalClicks"))
    if total <= 0:
        total = fb + li + tw
    network = _as_str(entry.get("network"))
    channel_key = _as_str(entry.get("channelKey"))
    title = _as_str(entry.get("name")) or f"Social post {post_id}"
    return HubSpotSocialPostRow(
        provider_post_id=post_id,
        platform=platform_from_network(network, channel_key),
        title=title[:500],
        facebook_clicks=fb,
        linkedin_clicks=li,
        twitter_clicks=tw,
        total_clicks=total,
        content_url=_as_str(entry.get("contentUrl")),
        posted_at=_parse_iso_datetime(entry.get("publishedAt")),
        channel_key=channel_key,
        network_label=network,
    )


def _row_from_social_broadcast_asset(entry: dict[str, Any]) -> HubSpotSocialPostRow | None:
    """Raw HubSpot ``assetsByType.SOCIAL_BROADCAST.results[]`` shape."""
    post_id = _as_str(entry.get("id"))
    if not post_id:
        # Some payloads use broadcastGuid
        post_id = _as_str(entry.get("broadcastGuid"))
    if not post_id:
        return None
    metrics = _as_record(entry.get("metrics")) or {}
    fb, li, tw = _clicks_from_asset_metrics(metrics)
    name = _as_str(entry.get("name")) or f"Social post {post_id}"
    network = _infer_network_from_asset(name, metrics)
    return HubSpotSocialPostRow(
        provider_post_id=post_id,
        platform=platform_from_network(network, None),
        title=name[:500],
        facebook_clicks=fb,
        linkedin_clicks=li,
        twitter_clicks=tw,
        total_clicks=fb + li + tw,
        content_url=None,
        posted_at=None,
        channel_key=None,
        network_label=network,
    )


def posts_from_hubspot_raw(raw: Any) -> list[HubSpotSocialPostRow]:
    """Prefer normalized ``socialPosts``; else parse ``assetsByType.SOCIAL_BROADCAST``."""
    snap = _as_record(raw)
    if snap is None:
        return []

    normalized = snap.get("socialPosts")
    if isinstance(normalized, list) and normalized:
        rows: list[HubSpotSocialPostRow] = []
        seen: set[tuple[str, str]] = set()
        for entry in normalized:
            record = _as_record(entry)
            if record is None:
                continue
            row = _row_from_normalized_social_post(record)
            if row is None:
                continue
            key = (row.platform, row.provider_post_id)
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
        if rows:
            return rows

    assets_by_type = _as_record(snap.get("assetsByType")) or {}
    social_raw = assets_by_type.get("SOCIAL_BROADCAST")
    # Older / alternate shapes
    if social_raw is None:
        social_raw = snap.get("socialBroadcast") or snap.get("SOCIAL_BROADCAST")
    social = _as_record(social_raw)
    results = social.get("results") if social else None
    if not isinstance(results, list):
        return []

    rows = []
    seen: set[tuple[str, str]] = set()
    for entry in results:
        record = _as_record(entry)
        if record is None:
            continue
        row = _row_from_social_broadcast_asset(record)
        if row is None:
            continue
        key = (row.platform, row.provider_post_id)
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return rows


def parse_hubspot_social_snapshot(raw: Any) -> HubSpotSocialSnapshot | None:
    """Return a snapshot DTO, or None when ``raw`` is not an object."""
    snap = _as_record(raw)
    if snap is None:
        return None
    hubspot_campaign_id = (
        _as_str(snap.get("hubspotCampaignId"))
        or _as_str(snap.get("hubspot_campaign_id"))
        or ""
    )
    return HubSpotSocialSnapshot(
        hubspot_campaign_id=hubspot_campaign_id,
        reporting_period_start=_parse_iso_date(snap.get("reportingPeriodStart")),
        reporting_period_end=_parse_iso_date(snap.get("reportingPeriodEnd")),
        posts=tuple(posts_from_hubspot_raw(snap)),
    )


@dataclass
class HubSpotIngestStats:
    """Result of ``ingest_campaign_hubspot_social``."""

    campaign_id: int
    posts: int = 0
    created: int = 0
    updated: int = 0
    metric_rows: int = 0
    links_created: int = 0
    links_reactivated: int = 0
    links_skipped_person: int = 0
    skipped: str | None = None


def _utc_today(now: datetime) -> date:
    if now.tzinfo is None:
        return now.date()
    return now.astimezone(timezone.utc).date()


def _metric_payload(row: HubSpotSocialPostRow) -> dict[str, Any]:
    return {
        "clicks": row.total_clicks,
        "facebookClicks": row.facebook_clicks,
        "linkedinClicks": row.linkedin_clicks,
        "twitterClicks": row.twitter_clicks,
    }


def _new_hubspot_post(row: HubSpotSocialPostRow, *, hubspot_campaign_id: str) -> Post:
    return Post(
        id=str(uuid.uuid4()),
        platform=row.platform,
        provider_post_id=row.provider_post_id,
        source=POST_SOURCE_HUBSPOT,
        content_type="social",
        title=row.title[:500],
        content_url=row.content_url,
        posted_at=row.posted_at,
        share_count=0,
        impression_count=0,
        view_count=0,
        like_count=0,
        comment_count=0,
        platform_metadata={
            "hubspotCampaignId": hubspot_campaign_id,
            "channelKey": row.channel_key,
            "network": row.network_label,
            "facebookClicks": row.facebook_clicks,
            "linkedinClicks": row.linkedin_clicks,
            "twitterClicks": row.twitter_clicks,
            "totalClicks": row.total_clicks,
        },
    )


async def _load_posts_for_hubspot_rows(
    db: AsyncSession, rows: list[HubSpotSocialPostRow]
) -> tuple[dict[tuple[str, str], Post], dict[str, list[Post]]]:
    """Load candidates for upsert.

    Returns:
      by_exact: (platform, provider_post_id) → post
      by_hubspot_provider_id: provider_post_id → all ``source=hubspot`` posts
        (any platform — in-place refine + demote prior duplicates)
    """
    ids = {row.provider_post_id for row in rows}
    if not ids:
        return {}, {}

    by_exact: dict[tuple[str, str], Post] = {}
    by_hubspot_provider_id: dict[str, list[Post]] = {}
    for post in (
        await db.execute(select(Post).where(Post.provider_post_id.in_(ids)))
    ).scalars():
        if not post.provider_post_id:
            continue
        by_exact[(post.platform, post.provider_post_id)] = post
        if post.source == POST_SOURCE_HUBSPOT:
            by_hubspot_provider_id.setdefault(post.provider_post_id, []).append(post)
    return by_exact, by_hubspot_provider_id


def _clear_hubspot_campaign_metadata(post: Post) -> None:
    """Stop EXTRA_RULE from re-linking a superseded duplicate row."""
    meta = dict(post.platform_metadata or {})
    meta.pop("hubspotCampaignId", None)
    meta.pop("hubspot_campaign_id", None)
    post.platform_metadata = meta or None


def _resolve_post_for_row(
    row: HubSpotSocialPostRow,
    *,
    by_exact: dict[tuple[str, str], Post],
    by_hubspot_provider_id: dict[str, list[Post]],
) -> tuple[Post | None, list[Post]]:
    """Pick the post to upsert; return any orphan duplicates to demote.

    Returns (target_or_None, orphans_to_demote).
    """
    exact = by_exact.get((row.platform, row.provider_post_id))
    hub_alts = list(by_hubspot_provider_id.get(row.provider_post_id) or [])

    if exact is not None:
        orphans = [p for p in hub_alts if p.id != exact.id]
        return exact, orphans

    if hub_alts:
        # Same HubSpot broadcast, platform refined (e.g. hubspot → linkedin).
        # Prefer an alt already on the target platform if present.
        preferred = next((p for p in hub_alts if p.platform == row.platform), hub_alts[0])
        orphans = [p for p in hub_alts if p.id != preferred.id]
        return preferred, orphans

    return None, []


async def _upsert_hubspot_metrics(
    db: AsyncSession,
    rows: list[tuple[str, date, dict[str, Any]]],
    *,
    now: datetime,
) -> int:
    """Upsert ``post_metrics_daily`` with source=hubspot, basis=lifetime_snapshot."""
    if not rows:
        return 0
    post_ids = {post_id for post_id, _, _ in rows}
    days = {day for _, day, _ in rows}
    existing = {
        (row.post_id, row.metric_date): row
        for row in (
            await db.execute(
                select(PostMetricDaily).where(
                    PostMetricDaily.post_id.in_(post_ids),
                    PostMetricDaily.metric_date >= min(days),
                    PostMetricDaily.metric_date <= max(days),
                    PostMetricDaily.source == METRICS_SOURCE_HUBSPOT,
                )
            )
        ).scalars()
    }
    for post_id, day, metrics in rows:
        row = existing.get((post_id, day))
        if row is None:
            row = PostMetricDaily(
                post_id=post_id,
                metric_date=day,
                source=METRICS_SOURCE_HUBSPOT,
                basis=METRICS_BASIS_HUBSPOT,
                metrics=metrics,
                fetched_at=now,
            )
            db.add(row)
            existing[(post_id, day)] = row
        else:
            row.basis = METRICS_BASIS_HUBSPOT
            row.metrics = metrics
            row.fetched_at = now
    await db.flush()
    return len(rows)


def _post_hubspot_guid(post: Post) -> str | None:
    meta = post.platform_metadata or {}
    return _as_str(meta.get("hubspotCampaignId")) or _as_str(meta.get("hubspot_campaign_id"))


def _campaigns_by_hubspot_guid(campaigns: list[Campaign]) -> dict[str, int]:
    """HubSpot GUID → campaign id (first owner wins; duplicates logged)."""
    owners: dict[str, list[int]] = {}
    for campaign in campaigns:
        guid = (campaign.hubspot_campaign_id or "").strip()
        if guid:
            owners.setdefault(guid, []).append(campaign.id)
    for guid, ids in owners.items():
        if len(ids) > 1:
            log.warning("hubspot_social_ingest_ambiguous_guid %s campaigns=%s", guid, ids)
    return {guid: ids[0] for guid, ids in owners.items()}


async def hubspot_campaign_extra_rule(
    db: AsyncSession, ctx: post_links.LinkContext
) -> list[post_links.Proposal]:
    """EXTRA_RULE: ``platform_metadata.hubspotCampaignId`` → ``campaigns.hubspot_campaign_id``."""
    del db  # signature matches ExtraRule; campaigns come from ctx
    by_guid = _campaigns_by_hubspot_guid(ctx.campaigns)
    if not by_guid:
        return []
    proposals: list[post_links.Proposal] = []
    for post in ctx.posts:
        guid = _post_hubspot_guid(post)
        if guid and guid in by_guid:
            proposals.append(
                post_links.Proposal(post.id, by_guid[guid], LINK_HUBSPOT_CAMPAIGN)
            )
    return proposals


def register_hubspot_link_rule() -> None:
    """Idempotent append onto ``post_links.EXTRA_RULES`` (no circular import)."""
    if hubspot_campaign_extra_rule not in post_links.EXTRA_RULES:
        post_links.EXTRA_RULES.append(hubspot_campaign_extra_rule)


async def _ensure_hubspot_links(
    db: AsyncSession,
    campaign: Campaign,
    post_ids: list[str],
) -> tuple[int, int, int]:
    """Ensure active ``hubspot_campaign`` links; respect manual / person-removed.

    Returns (created, reactivated, skipped_person).
    """
    if not post_ids:
        return 0, 0, 0
    existing = {
        link.post_id: link
        for link in (
            await db.execute(
                select(PostCampaignLink).where(
                    PostCampaignLink.campaign_id == campaign.id,
                    PostCampaignLink.post_id.in_(post_ids),
                )
            )
        ).scalars()
    }
    created = reactivated = skipped_person = 0
    confidence = post_links._CONFIDENCE.get(LINK_HUBSPOT_CAMPAIGN)
    for post_id in post_ids:
        link = existing.get(post_id)
        if link is None:
            db.add(
                PostCampaignLink(
                    post_id=post_id,
                    campaign_id=campaign.id,
                    method=LINK_HUBSPOT_CAMPAIGN,
                    confidence=confidence,
                    status=LINK_ACTIVE,
                    created_by=post_links.LINKER,
                )
            )
            created += 1
            continue
        if link.method == LINK_MANUAL:
            continue
        if link.status == LINK_REMOVED and link.removed_by != post_links.LINKER:
            skipped_person += 1
            continue
        if link.status != LINK_ACTIVE:
            link.status = LINK_ACTIVE
            link.removed_by = None
            link.removed_at = None
            reactivated += 1
        link.method = LINK_HUBSPOT_CAMPAIGN
        link.confidence = confidence
    await db.flush()
    return created, reactivated, skipped_person


async def ingest_campaign_hubspot_social(
    db: AsyncSession,
    campaign: Campaign,
    *,
    now: datetime | None = None,
) -> HubSpotIngestStats:
    """Upsert HubSpot social posts, click metrics, and campaign links.

    Soft no-op when there is no GUID, no snapshot, or no social rows — never
    raises for empty payload. Person-removed / manual links are left alone.
    """
    register_hubspot_link_rule()
    now = now or datetime.now(timezone.utc)
    stats = HubSpotIngestStats(campaign_id=campaign.id)

    guid = (campaign.hubspot_campaign_id or "").strip()
    if not guid:
        stats.skipped = "no_hubspot_campaign_id"
        return stats

    snapshot = parse_hubspot_social_snapshot(campaign.hubspot_raw_data)
    if snapshot is None or not snapshot.posts:
        stats.skipped = "no_social_payload"
        return stats

    # Always stamp the Hub campaign row GUID so EXTRA_RULE cannot relocate
    # links when snapshot.hubspotCampaignId disagrees (copied/stale payload).
    if (
        snapshot.hubspot_campaign_id
        and snapshot.hubspot_campaign_id != guid
    ):
        log.warning(
            "hubspot_social_ingest_guid_mismatch campaign_id=%s "
            "campaign_guid=%s snapshot_guid=%s (using campaign row)",
            campaign.id,
            guid,
            snapshot.hubspot_campaign_id,
        )
    hubspot_campaign_id = guid
    metric_date = snapshot.reporting_period_end or _utc_today(now)
    rows = list(snapshot.posts)
    by_exact, by_hubspot_provider_id = await _load_posts_for_hubspot_rows(db, rows)

    metric_rows: list[tuple[str, date, dict[str, Any]]] = []
    post_ids: list[str] = []
    for row in rows:
        key = (row.platform, row.provider_post_id)
        post, orphans = _resolve_post_for_row(
            row, by_exact=by_exact, by_hubspot_provider_id=by_hubspot_provider_id
        )
        for orphan in orphans:
            _clear_hubspot_campaign_metadata(orphan)

        if post is None:
            post = _new_hubspot_post(row, hubspot_campaign_id=hubspot_campaign_id)
            db.add(post)
            by_exact[key] = post
            by_hubspot_provider_id[row.provider_post_id] = [post]
            stats.created += 1
        else:
            stats.updated += 1
            if post.platform != row.platform:
                # In-place platform refine (hubspot → linkedin after enrich).
                # Safe: exact (row.platform, id) was absent when we resolved.
                old_key = (post.platform, post.provider_post_id or row.provider_post_id)
                post.platform = row.platform
                by_exact.pop(old_key, None)
                by_exact[key] = post
            post.title = row.title[:500]
            if row.content_url:
                post.content_url = row.content_url
            if row.posted_at is not None:
                post.posted_at = row.posted_at
            if post.source != POST_SOURCE_HUBSPOT and post.source:
                # Keep non-hubspot provenance; still attach HubSpot metadata + metrics.
                pass
            else:
                post.source = POST_SOURCE_HUBSPOT
                post.content_type = post.content_type or "social"
                by_hubspot_provider_id[row.provider_post_id] = [post] + [
                    p
                    for p in (by_hubspot_provider_id.get(row.provider_post_id) or [])
                    if p.id != post.id
                ]

        meta = dict(post.platform_metadata or {})
        meta.update(
            {
                "hubspotCampaignId": hubspot_campaign_id,
                "channelKey": row.channel_key,
                "network": row.network_label,
                "facebookClicks": row.facebook_clicks,
                "linkedinClicks": row.linkedin_clicks,
                "twitterClicks": row.twitter_clicks,
                "totalClicks": row.total_clicks,
            }
        )
        post.platform_metadata = meta
        post.stats_synced_at = now
        # Need id before metrics; new posts get id at construction.
        metric_rows.append((post.id, metric_date, _metric_payload(row)))
        post_ids.append(post.id)

    await db.flush()
    stats.posts = len(rows)
    stats.metric_rows = await _upsert_hubspot_metrics(db, metric_rows, now=now)
    (
        stats.links_created,
        stats.links_reactivated,
        stats.links_skipped_person,
    ) = await _ensure_hubspot_links(db, campaign, post_ids)
    log.info(
        "hubspot_social_ingest campaign=%s posts=%s created=%s updated=%s metrics=%s "
        "links_created=%s links_reactivated=%s links_skipped_person=%s",
        campaign.id,
        stats.posts,
        stats.created,
        stats.updated,
        stats.metric_rows,
        stats.links_created,
        stats.links_reactivated,
        stats.links_skipped_person,
    )
    return stats


@dataclass
class HubSpotBackfillStats:
    """Result of ``ingest_all_campaigns_with_hubspot`` (snapshot backfill)."""

    campaigns: int = 0
    ingested: int = 0
    skipped: int = 0
    posts_created: int = 0
    posts_updated: int = 0
    metric_rows: int = 0
    links_created: int = 0
    errors: list[str] = field(default_factory=list)


async def ingest_all_campaigns_with_hubspot(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> HubSpotBackfillStats:
    """Backfill HubSpot social from stored ``hubspot_raw_data`` (no HubSpot HTTP).

    Soft per-campaign errors — one bad campaign does not stop the rest.
    """
    register_hubspot_link_rule()
    now = now or datetime.now(timezone.utc)
    stats = HubSpotBackfillStats()
    campaigns = list(
        (
            await db.execute(
                select(Campaign).where(
                    Campaign.hubspot_campaign_id != "",
                    Campaign.hubspot_raw_data.is_not(None),
                )
            )
        ).scalars()
    )
    for campaign in campaigns:
        stats.campaigns += 1
        try:
            result = await ingest_campaign_hubspot_social(db, campaign, now=now)
        except Exception as exc:
            log.exception(
                "hubspot_social_backfill_failed campaign_id=%s", campaign.id
            )
            stats.errors.append(f"campaign {campaign.id}: {exc}")
            continue
        if result.skipped:
            stats.skipped += 1
            continue
        stats.ingested += 1
        stats.posts_created += result.created
        stats.posts_updated += result.updated
        stats.metric_rows += result.metric_rows
        stats.links_created += result.links_created
    log.info(
        "hubspot_social_backfill campaigns=%s ingested=%s skipped=%s errors=%s "
        "posts_created=%s metric_rows=%s links_created=%s",
        stats.campaigns,
        stats.ingested,
        stats.skipped,
        len(stats.errors),
        stats.posts_created,
        stats.metric_rows,
        stats.links_created,
    )
    return stats


# Register for nightly ``post_links.relink`` whenever this module is imported.
register_hubspot_link_rule()
