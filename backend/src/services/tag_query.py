"""Namespaced tag filter semantics (SCRUM-77 + WP-projection filter).

Public read endpoints (`/api/public/clips?tag=…`, `/api/public/playlists?tag=…`)
accept a comma-separated tag list. Historical behavior was pure AND across
every listed tag — the wrong semantics for CHT's focus chips, which want
UNION within a namespace. Example:

  ?tag=biomarker:her2-low,biomarker:her2-ultra-low,drug:t-dxd

should return rows that have (biomarker in [her2-low OR her2-ultra-low])
AND (drug in [t-dxd]) — not rows that carry *all three* tags simultaneously.

## WP-projected namespaces (added 2026-07-21)

`/api/public/tags` now also surfaces WordPress editorial tags:
- `topic:*` values come from `wordpress_events.categories`
- `wp:*`    values come from `wordpress_events.tags`

For `/api/public/clips?tag=topic:her2`, we can't rely on Clip.tags alone
because most clips don't have the WP-derived tag stored locally. Instead
we partition the requested tag list into own-Clip.tags namespaces vs
WP-projected namespaces, and filter each source separately in the
query. See `partition_wp_projected_tags` + `WP_PROJECTED_NAMESPACES`.

## Public entry points

- `group_tags_by_namespace(tags_list)` — {namespace: [tags]}, insertion order
- `partition_wp_projected_tags(tags_list)` — (clip_side, wp_topic, wp_tag)
- `postgres_tag_filter(tag_column, tags_list)` — SCRUM-77 AND/OR clause
- `python_row_matches(row_tags, tags_list)` — SQLite/test equivalent
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import String as SAString, and_, cast, or_
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY

# Namespaces whose values are sourced from WordPress editorial state, not
# from Clip.tags directly. Filter path for these must join wordpress_events.
# See public/clips.py for the query construction.
WP_PROJECTED_NAMESPACES: frozenset[str] = frozenset({"topic", "wp"})


def group_tags_by_namespace(tags_list: list[str]) -> dict[str, list[str]]:
    """{namespace: [tag1, tag2, ...]} preserving order.

    Tags without a `:` are placed under the empty-string namespace so
    the caller can decide whether to reject them or fall through to a
    substring match (current behavior in some routes).
    """
    grouped: dict[str, list[str]] = defaultdict(list)
    for tag in tags_list:
        if not tag:
            continue
        ns, _, _ = tag.partition(":")
        grouped[ns].append(tag)
    return dict(grouped)


def postgres_tag_filter(tag_column, tags_list: list[str]):
    """AND across namespaces, OR within a namespace. Postgres-only.

    Returns a SQLAlchemy boolean clause, or None if `tags_list` is empty.
    Wrap the return value in `query.where(...)` at the call site.
    """
    if not tags_list:
        return None
    grouped = group_tags_by_namespace(tags_list)
    pg_array = cast(tag_column, PG_ARRAY(SAString))
    namespace_clauses = []
    for _ns, tags_in_ns in grouped.items():
        if len(tags_in_ns) == 1:
            namespace_clauses.append(pg_array.any(tags_in_ns[0]))
        else:
            namespace_clauses.append(or_(*(pg_array.any(t) for t in tags_in_ns)))
    return and_(*namespace_clauses)


def python_row_matches(row_tags: list[str] | None, tags_list: list[str]) -> bool:
    """SQLite fallback: does `row_tags` satisfy the (AND-across, OR-within) query?

    Empty tags_list ⇒ True (no filter). Empty row_tags with a non-empty
    tags_list ⇒ False.
    """
    if not tags_list:
        return True
    row_set = set(row_tags or [])
    for _ns, tags_in_ns in group_tags_by_namespace(tags_list).items():
        if not any(t in row_set for t in tags_in_ns):
            return False
    return True


def partition_wp_projected_tags(
    tags_list: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """Split a filter list into three buckets by source namespace.

    - clip_side: tags whose ns is NOT in WP_PROJECTED_NAMESPACES; check
      against Clip.tags directly.
    - wp_topic_values: for `topic:X` entries — check `wordpress_events.categories`
      contains `X` (bare value, no namespace prefix, matching WP's stored form).
    - wp_tag_values: for `wp:X` entries — check `wordpress_events.tags`
      contains `X` (bare value).

    Each bucket's semantics is OR-within (matches SCRUM-77). Callers apply
    AND across the three buckets so the combined filter matches the ticket
    example.
    """
    clip_side: list[str] = []
    wp_topic_values: list[str] = []
    wp_tag_values: list[str] = []
    for tag in tags_list:
        if not tag:
            continue
        ns, _, value = tag.partition(":")
        ns = ns.strip()
        value = value.strip()
        if not ns or not value:
            clip_side.append(tag)
            continue
        if ns == "topic":
            wp_topic_values.append(value)
        elif ns == "wp":
            wp_tag_values.append(value)
        else:
            clip_side.append(tag)
    return clip_side, wp_topic_values, wp_tag_values
