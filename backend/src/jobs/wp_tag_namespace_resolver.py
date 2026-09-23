"""Resolver: projects a WP tag slug onto its namespaced form (WPR-11).

Called from two places:
  1. Ingest projection — when a post event lands, tags get projected into
     namespaced form (used by future filter surfaces / CHT read paths).
  2. Read endpoint (`/api/public/wordpress/tags`) — returns both raw and
     projected form so consumers can choose.

Resolution priority:
  1. Look up in `wp_tag_namespace_map` (DB — curator + rule-seeded).
  2. Fall back to inline rulebook (`wp_tag_namespace_rulebook.classify_wp_tag`).
  3. Fall back to `wp:<slug>` (never lose a tag).

Priority ordering matters: DB rows take precedence over the inline rules
because the DB row may represent a curator override that supersedes the
rule (e.g., an ambiguous slug the rule classifies one way but the curator
overrides).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class NamespacedTag:
    """One projected tag — `namespace:value` pair with provenance."""

    namespace: str
    value: str
    source: str  # 'db' | 'rule' | 'wp_fallback'

    def as_qualified(self) -> str:
        """Serialized form: e.g. 'biomarker:HER2+' or 'wp:her2-therapy'."""
        return f"{self.namespace}:{self.value}"


async def resolve_wp_tag(
    db: AsyncSession, slug: str
) -> NamespacedTag:
    """Resolve one WP tag slug to its namespaced form.

    DB lookup → rulebook fallback → wp:<slug> fallback. Never returns None
    (the fallback path guarantees a resolution).
    """
    from jobs.wp_tag_namespace_rulebook import classify_wp_tag
    from models.wp_tag_namespace_map import WpTagNamespaceMap

    if not slug:
        return NamespacedTag(namespace="wp", value="", source="wp_fallback")

    slug = slug.strip().lower()

    # 1. DB lookup.
    row = (
        await db.execute(
            select(WpTagNamespaceMap).where(
                WpTagNamespaceMap.wp_tag_slug == slug
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        return NamespacedTag(
            namespace=row.canonical_namespace,
            value=row.canonical_value,
            source="db",
        )

    # 2. Inline rulebook fallback.
    rule_result = classify_wp_tag(slug)
    if rule_result is not None:
        return NamespacedTag(
            namespace=rule_result.namespace,
            value=rule_result.value,
            source="rule",
        )

    # 3. Never lose a tag — fall back to wp:<slug>.
    return NamespacedTag(namespace="wp", value=slug, source="wp_fallback")


async def resolve_wp_tags_batch(
    db: AsyncSession, slugs: list[str]
) -> dict[str, NamespacedTag]:
    """Batched resolver — one DB round-trip regardless of how many slugs."""
    from jobs.wp_tag_namespace_rulebook import classify_wp_tag
    from models.wp_tag_namespace_map import WpTagNamespaceMap

    slugs = [s.strip().lower() for s in slugs if s]
    if not slugs:
        return {}

    # 1. Bulk DB lookup.
    rows = (
        await db.execute(
            select(WpTagNamespaceMap).where(
                WpTagNamespaceMap.wp_tag_slug.in_(slugs)
            )
        )
    ).scalars().all()
    by_slug: dict[str, NamespacedTag] = {
        r.wp_tag_slug: NamespacedTag(
            namespace=r.canonical_namespace,
            value=r.canonical_value,
            source="db",
        )
        for r in rows
    }

    # 2. Fill gaps via rulebook + wp: fallback.
    for slug in slugs:
        if slug in by_slug:
            continue
        rule_result = classify_wp_tag(slug)
        if rule_result is not None:
            by_slug[slug] = NamespacedTag(
                namespace=rule_result.namespace,
                value=rule_result.value,
                source="rule",
            )
        else:
            by_slug[slug] = NamespacedTag(
                namespace="wp", value=slug, source="wp_fallback"
            )

    return by_slug
