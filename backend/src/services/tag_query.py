"""Namespaced tag filter semantics (SCRUM-77).

Public read endpoints (`/api/public/clips?tag=…`, `/api/public/playlists?tag=…`)
accept a comma-separated tag list. Historical behavior was pure AND across
every listed tag — the wrong semantics for CHT's focus chips, which want
UNION within a namespace. Example:

  ?tag=biomarker:her2-low,biomarker:her2-ultra-low,drug:t-dxd

should return rows that have (biomarker in [her2-low OR her2-ultra-low])
AND (drug in [t-dxd]) — not rows that carry *all three* tags simultaneously.

This module exposes:

- `group_tags_by_namespace(tags_list)` — pure helper that returns a
  {namespace: [tags]} dict, preserving insertion order. Malformed tags
  (no `:`) become their own single-value group under their full string,
  which effectively requires an exact match if present in a row.
- `postgres_tag_filter(tag_column, tags_list)` — builds an SQLAlchemy
  filter clause (AND-across-namespace, OR-within-namespace) suitable for
  a `.where(...)` argument.
- `python_row_matches(row_tags, tags_list)` — SQLite/test fallback that
  checks the same semantics against a row's tag list in memory.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import String as SAString, and_, cast, or_
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY


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
