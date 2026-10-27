"""Automatic post → campaign links (CPR-15).

Rules, strongest first; a post's link to a campaign records the first rule
that found it:

1. ``campaign_map`` — integration ``campaignMap[campaign].youtubeVideoIds``
   (videos) and ``linkedinCampaignIds`` (every ad in those ad campaigns).
2. ``content_id`` — a CHM Content ID (``RIG-26-02_VEP_SPL2``) in the post's
   title, description or URL, or its LinkedIn ad campaign's name, that
   belongs to exactly one campaign. A campaign's IDs come from its tags,
   name and program name.
3. ``wordpress_embed`` — the same, read from the WordPress articles that
   embed the YouTube video.
4. ``shoot`` — the post's shoot is mapped to a campaign.
5. ``promoted_post`` — an ad and the organic post it promotes share their
   links from rules 1–4.

``EXTRA_RULES`` lets other sources add proposals (CPR-56 HubSpot campaign
GUID map via ``hubspot_campaign``). Manual links are never changed: a manual
link, active or removed, blocks any automatic link for the same post and
campaign. An automatic link that no rule supports any more is marked removed
by ``linker``; a link a person removed stays removed.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.campaign import Campaign, IntegrationSetting
from models.export_warehouse import ExportSession
from models.post import Post
from models.shoot import Shoot
from models.social import (
    LINK_ACTIVE,
    LINK_CAMPAIGN_MAP,
    LINK_CONTENT_ID,
    LINK_HUBSPOT_CAMPAIGN,
    LINK_MANUAL,
    LINK_PROMOTED_POST,
    LINK_REMOVED,
    LINK_SHOOT,
    LINK_WORDPRESS_EMBED,
    PostCampaignLink,
)
from models.wordpress_projection import WordPressPost
from services.connectors.common import mapped_ids

log = logging.getLogger(__name__)

LINKER = "linker"

# v1.1 Program Registry format: CLIENT-YY-SS_TOPIC_FMTn (e.g. RIG-26-02_VEP_SPL2).
CONTENT_ID = re.compile(r"(?<![A-Z0-9])([A-Z]{2,4}-\d{2}-\d{2}_[A-Z0-9]{2,4}_[A-Z]{3}\d{1,2})(?![A-Z0-9])")

_CONFIDENCE = {
    LINK_CAMPAIGN_MAP: 1.0,
    LINK_CONTENT_ID: 1.0,
    LINK_WORDPRESS_EMBED: 0.9,
    LINK_SHOOT: 0.9,
    LINK_PROMOTED_POST: 1.0,
    LINK_HUBSPOT_CAMPAIGN: 1.0,
}


@dataclass(frozen=True)
class Proposal:
    post_id: str
    campaign_id: int
    method: str
    chm_content_id: str | None = None


@dataclass
class LinkContext:
    posts: list[Post]
    campaigns: list[Campaign]


@dataclass
class RelinkStats:
    created: int = 0
    reactivated: int = 0
    updated: int = 0
    removed: int = 0
    active: int = 0
    # Automatic links in place after the run, by the rule that made them.
    by_method: dict[str, int] = field(default_factory=dict)


@dataclass
class ApplyProposalStats:
    """Result of ``apply_proposals`` (create / reactivate only; no removals)."""

    created: int = 0
    reactivated: int = 0
    updated: int = 0
    skipped_person: int = 0
    skipped_other_method: int = 0
    by_method: dict[str, int] = field(default_factory=dict)


ExtraRule = Callable[[AsyncSession, LinkContext], Awaitable[list[Proposal]]]
EXTRA_RULES: list[ExtraRule] = []


def content_ids(*texts: str | None) -> list[str]:
    found: list[str] = []
    for text in texts:
        for match in CONTENT_ID.findall(text or ""):
            if match not in found:
                found.append(match)
    return found


def _campaign_content_ids(campaigns: list[Campaign]) -> dict[str, int]:
    """Content ID → campaign, for IDs that belong to exactly one campaign."""
    owners: dict[str, set[int]] = {}
    for campaign in campaigns:
        for cid in content_ids(campaign.name, campaign.program_name, *(campaign.tags or [])):
            owners.setdefault(cid, set()).add(campaign.id)
    ambiguous = sorted(cid for cid, ids in owners.items() if len(ids) > 1)
    if ambiguous:
        log.warning("post_links_ambiguous_content_ids %s", ambiguous)
    return {cid: next(iter(ids)) for cid, ids in owners.items() if len(ids) == 1}


async def _rule_proposals(db: AsyncSession, ctx: LinkContext) -> list[Proposal]:
    proposals: list[Proposal] = []
    campaign_ids = {campaign.id for campaign in ctx.campaigns}
    youtube_posts = {p.provider_post_id: p for p in ctx.posts if p.platform == "youtube"}

    # 1. campaignMap
    youtube_config = await db.get(IntegrationSetting, "youtube")
    linkedin_config = await db.get(IntegrationSetting, "linkedin")
    youtube_map = youtube_config.value_json if youtube_config else {}
    linkedin_map = linkedin_config.value_json if linkedin_config else {}
    ads_by_campaign: dict[str, list[Post]] = {}
    for post in ctx.posts:
        ad_campaign = (post.platform_metadata or {}).get("adCampaignId")
        if post.platform == "linkedin" and ad_campaign:
            ads_by_campaign.setdefault(str(ad_campaign), []).append(post)
    for campaign_id in campaign_ids:
        for video_id in mapped_ids(youtube_map, campaign_id, "youtubeVideoIds"):
            post = youtube_posts.get(video_id)
            if post is not None:
                proposals.append(Proposal(post.id, campaign_id, LINK_CAMPAIGN_MAP))
        for ad_campaign in mapped_ids(linkedin_map, campaign_id, "linkedinCampaignIds"):
            for post in ads_by_campaign.get(ad_campaign.rsplit(":", 1)[-1], []):
                proposals.append(Proposal(post.id, campaign_id, LINK_CAMPAIGN_MAP))

    # 2. Content ID in the post (or its ad campaign's name)
    by_content_id = _campaign_content_ids(ctx.campaigns)
    for post in ctx.posts:
        ad_campaign_name = (post.platform_metadata or {}).get("adCampaignName")
        for cid in content_ids(post.title, post.description, post.content_url, ad_campaign_name):
            if cid in by_content_id:
                proposals.append(Proposal(post.id, by_content_id[cid], LINK_CONTENT_ID, cid))

    # 3. Content ID in a WordPress article that embeds the video
    articles = (
        await db.execute(
            select(
                WordPressPost.youtube_video_id,
                WordPressPost.title,
                WordPressPost.slug,
                WordPressPost.permalink,
            ).where(
                WordPressPost.youtube_video_id.is_not(None),
                WordPressPost.deleted_at.is_(None),
            )
        )
    ).all()
    for video_id, title, slug, permalink in articles:
        post = youtube_posts.get(video_id)
        if post is None:
            continue
        for cid in content_ids(title, (slug or "").upper(), (permalink or "").upper()):
            if cid in by_content_id:
                proposals.append(Proposal(post.id, by_content_id[cid], LINK_WORDPRESS_EMBED, cid))

    # 4. Shoot mapped to a campaign
    shoot_campaigns = dict(
        (
            await db.execute(
                select(Shoot.id, Shoot.campaign_id).where(Shoot.campaign_id.is_not(None))
            )
        ).all()
    )
    for post in ctx.posts:
        campaign_id = shoot_campaigns.get(post.shoot_id) if post.shoot_id else None
        if campaign_id is not None:
            proposals.append(Proposal(post.id, campaign_id, LINK_SHOOT))

    return proposals


def _promoted(posts: list[Post], proposals: list[Proposal]) -> list[Proposal]:
    """An ad and the organic post it promotes take each other's campaigns."""
    by_post: dict[str, list[Proposal]] = {}
    for proposal in proposals:
        by_post.setdefault(proposal.post_id, []).append(proposal)
    shared: list[Proposal] = []
    for ad in posts:
        if not ad.promotes_post_id:
            continue
        for source, target in ((ad.promotes_post_id, ad.id), (ad.id, ad.promotes_post_id)):
            shared += [
                Proposal(target, proposal.campaign_id, LINK_PROMOTED_POST, proposal.chm_content_id)
                for proposal in by_post.get(source, [])
            ]
    return shared


async def _single_programs(db: AsyncSession) -> dict[int, str]:
    """Campaign → Platform program, for campaigns with exactly one program."""
    programs: dict[int, set[str]] = {}
    for campaign_id, program_id in (
        await db.execute(
            select(ExportSession.campaign_id, ExportSession.platform_tool_program_id).where(
                ExportSession.campaign_id.is_not(None)
            )
        )
    ).all():
        programs.setdefault(campaign_id, set()).add(program_id)
    return {cid: next(iter(ids)) for cid, ids in programs.items() if len(ids) == 1}


async def apply_proposals(
    db: AsyncSession,
    proposals: list[Proposal],
    *,
    overwrite_method: bool = True,
) -> ApplyProposalStats:
    """Create / reactivate automatic links for ``proposals`` (shared by relink + HubSpot).

    Manual and person-removed links are never changed. When
    ``overwrite_method`` is False, an active link owned by another automatic
    rule (e.g. ``content_id``) is left alone so HubSpot ingest cannot churn
    ``method`` nightly against ``relink``.
    """
    stats = ApplyProposalStats()
    if not proposals:
        return stats

    programs = await _single_programs(db)
    post_ids = {p.post_id for p in proposals}
    campaign_ids = {p.campaign_id for p in proposals}
    existing = {
        (link.post_id, link.campaign_id): link
        for link in (
            await db.execute(
                select(PostCampaignLink).where(
                    PostCampaignLink.post_id.in_(post_ids),
                    PostCampaignLink.campaign_id.in_(campaign_ids),
                )
            )
        ).scalars()
    }

    for proposal in proposals:
        key = (proposal.post_id, proposal.campaign_id)
        link = existing.get(key)
        program_id = programs.get(proposal.campaign_id)
        if link is None:
            link = PostCampaignLink(
                post_id=proposal.post_id,
                campaign_id=proposal.campaign_id,
                platform_program_id=program_id,
                chm_content_id=proposal.chm_content_id,
                method=proposal.method,
                confidence=_CONFIDENCE.get(proposal.method),
                status=LINK_ACTIVE,
                created_by=LINKER,
            )
            db.add(link)
            existing[key] = link
            stats.created += 1
            stats.by_method[proposal.method] = (
                stats.by_method.get(proposal.method, 0) + 1
            )
            continue
        if link.method == LINK_MANUAL:
            continue
        if link.status == LINK_REMOVED and link.removed_by != LINKER:
            stats.skipped_person += 1
            continue
        if (
            not overwrite_method
            and link.status == LINK_ACTIVE
            and link.method != proposal.method
        ):
            stats.skipped_other_method += 1
            continue
        if link.status != LINK_ACTIVE:
            link.status = LINK_ACTIVE
            link.removed_by = None
            link.removed_at = None
            stats.reactivated += 1
        elif (link.method, link.chm_content_id, link.platform_program_id) != (
            proposal.method,
            proposal.chm_content_id,
            program_id,
        ):
            stats.updated += 1
        link.method = proposal.method
        link.chm_content_id = proposal.chm_content_id
        link.platform_program_id = program_id
        link.confidence = _CONFIDENCE.get(proposal.method)
        stats.by_method[proposal.method] = stats.by_method.get(proposal.method, 0) + 1

    await db.flush()
    return stats


async def relink(db: AsyncSession, *, now: datetime | None = None) -> RelinkStats:
    """Recompute automatic links for every post."""
    now = now or datetime.now(timezone.utc)
    # CPR-56: ensure HubSpot GUID EXTRA_RULE is registered (lazy, no cycle at import).
    from services import hubspot_social_ingest as _hubspot_social_ingest  # noqa: PLC0415

    _hubspot_social_ingest.register_hubspot_link_rule()
    ctx = LinkContext(
        posts=list((await db.execute(select(Post).where(Post.excluded.is_(False)))).scalars()),
        campaigns=list((await db.execute(select(Campaign))).scalars()),
    )
    proposals = await _rule_proposals(db, ctx)
    for rule in EXTRA_RULES:
        proposals += await rule(db, ctx)
    proposals += _promoted(ctx.posts, proposals)

    wanted: dict[tuple[str, int], Proposal] = {}
    for proposal in proposals:
        wanted.setdefault((proposal.post_id, proposal.campaign_id), proposal)

    existing = {
        (link.post_id, link.campaign_id): link
        for link in (await db.execute(select(PostCampaignLink))).scalars()
    }
    stats = RelinkStats()

    for key, link in existing.items():
        if link.method == LINK_MANUAL or key in wanted:
            continue
        if link.status != LINK_REMOVED:
            link.status = LINK_REMOVED
            link.removed_by = LINKER
            link.removed_at = now
            stats.removed += 1

    applied = await apply_proposals(
        db, list(wanted.values()), overwrite_method=True
    )
    stats.created = applied.created
    stats.reactivated = applied.reactivated
    stats.updated = applied.updated
    stats.by_method = applied.by_method

    stats.active = (
        await db.execute(
            select(func.count()).select_from(PostCampaignLink).where(
                PostCampaignLink.status == LINK_ACTIVE
            )
        )
    ).scalar_one()
    return stats
