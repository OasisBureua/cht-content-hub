"""seed_tag_namespace — one of the ops under wordpress_projection_ops.

Populates `wp_tag_namespace_map` by running the rulebook against every
WP tag currently in `wordpress_tags` (Layer 2). Skips slugs that already
have a curator-sourced row (source != 'rule') so this op never overwrites
an editorial decision.

Idempotent: re-invocations produce zero net writes if the rulebook + tag
inventory haven't changed.

Payload (all optional):
    {
      "op": "seed_tag_namespace",
      "dry_run": false,             # report what WOULD be written
      "overwrite_rules": false,     # rewrite existing rule-sourced rows too
                                    # (useful when the rulebook itself changes)
    }
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


async def _fetch_all_wp_tag_slugs() -> list[str]:
    from database import async_session_maker
    from models.wordpress_projection import WordPressTag
    from sqlalchemy import select

    async with async_session_maker() as db:
        rows = (
            await db.execute(
                select(WordPressTag.slug).where(
                    WordPressTag.deleted_at.is_(None)
                )
            )
        ).scalars().all()
    return list(rows)


async def _fetch_existing_map() -> dict[str, str]:
    """{slug: source} for every row currently in the map — for skip logic."""
    from database import async_session_maker
    from models.wp_tag_namespace_map import WpTagNamespaceMap
    from sqlalchemy import select

    async with async_session_maker() as db:
        rows = (
            await db.execute(
                select(WpTagNamespaceMap.wp_tag_slug, WpTagNamespaceMap.source)
            )
        ).all()
    return {slug: source for slug, source in rows}


async def _upsert_mappings(
    to_write: dict[str, tuple[str, str, str]], overwrite_rules: bool
) -> tuple[int, int]:
    """Insert / update wp_tag_namespace_map rows. Returns (inserted, updated).

    to_write: {slug: (namespace, value, source)}
    """
    from database import async_session_maker
    from models.wp_tag_namespace_map import WpTagNamespaceMap
    from sqlalchemy import select

    inserted = 0
    updated = 0

    async with async_session_maker() as db:
        for slug, (namespace, value, source) in to_write.items():
            existing = (
                await db.execute(
                    select(WpTagNamespaceMap).where(
                        WpTagNamespaceMap.wp_tag_slug == slug
                    )
                )
            ).scalar_one_or_none()

            if existing is None:
                db.add(
                    WpTagNamespaceMap(
                        wp_tag_slug=slug,
                        canonical_namespace=namespace,
                        canonical_value=value,
                        source=source,
                    )
                )
                inserted += 1
            elif existing.source == "rule" and (
                overwrite_rules
                or existing.canonical_namespace != namespace
                or existing.canonical_value != value
            ):
                existing.canonical_namespace = namespace
                existing.canonical_value = value
                existing.source = source
                updated += 1
            # else: curator-sourced or unchanged rule row — leave alone.
        await db.commit()

    return inserted, updated


async def run(event: dict[str, Any]) -> dict[str, Any]:
    from jobs.wp_tag_namespace_rulebook import classify_batch

    dry_run = bool(event.get("dry_run", False))
    overwrite_rules = bool(event.get("overwrite_rules", False))

    log.info(
        "seed_tag_namespace start",
        extra={"dry_run": dry_run, "overwrite_rules": overwrite_rules},
    )

    slugs = await _fetch_all_wp_tag_slugs()
    if not slugs:
        return {
            "status": "ok",
            "op": "seed_tag_namespace",
            "reason": "no WP tags in wordpress_tags — nothing to seed",
        }

    existing_map = await _fetch_existing_map()

    # Classify + collect writes.
    rulebook_matches = classify_batch(slugs)
    to_write: dict[str, tuple[str, str, str]] = {}
    unmapped: list[str] = []

    for slug in slugs:
        # Never touch curator-sourced rows.
        if existing_map.get(slug) not in (None, "rule"):
            continue

        result = rulebook_matches.get(slug)
        if result is None:
            unmapped.append(slug)
            continue

        to_write[slug] = (result.namespace, result.value, result.source)

    log.info(
        "seed_tag_namespace classified",
        extra={
            "total_slugs": len(slugs),
            "rule_matches": len(rulebook_matches),
            "will_write": len(to_write),
            "unmapped_wp_fallback": len(unmapped),
        },
    )

    if dry_run:
        return {
            "status": "ok",
            "op": "seed_tag_namespace",
            "dry_run": True,
            "total_slugs": len(slugs),
            "rule_matches": len(rulebook_matches),
            "would_write": len(to_write),
            "unmapped_wp_fallback": len(unmapped),
            "sample_writes": [
                {"slug": s, "namespace": ns, "value": v}
                for s, (ns, v, _src) in list(to_write.items())[:10]
            ],
            "sample_unmapped": unmapped[:10],
        }

    inserted, updated = await _upsert_mappings(to_write, overwrite_rules)

    log.info(
        "seed_tag_namespace done",
        extra={"inserted": inserted, "updated": updated},
    )

    return {
        "status": "ok",
        "op": "seed_tag_namespace",
        "total_slugs": len(slugs),
        "rule_matches": len(rulebook_matches),
        "inserted": inserted,
        "updated": updated,
        "unmapped_wp_fallback": len(unmapped),
    }
