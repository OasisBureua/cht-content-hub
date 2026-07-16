"""KOL profile field-update helper with curated-fields guard.

Central write point for KOL editable fields. Two callers today:

1. Admin PATCH `/api/admin/kols/{slug}` → `source="admin"`. Applies every
   field in the update and marks each one curated in `KOL.curated_fields`
   so future sync writes cannot silently overwrite it.
2. Enrichment sync jobs (future — no writers exist yet as of SCRUM-61) →
   `source="sync"`. Applies only fields NOT already curated by an admin.

Mirrors the `hcp_match_status` "manually_locked" guard pattern used at
hcp_intel/openalex_backfill.py:103 — same "sync respects manual lock" idea.

The editable-field allowlist is enforced here (rather than in the schema)
so both admin and sync callers get identical protection against writing
random attributes.
"""

from __future__ import annotations

from typing import Any, Iterable, Literal

from models.kol import KOL
from services import kol_regions

# Fields an admin is allowed to edit via the admin API. Any key outside
# this set is silently ignored by `apply_kol_field_update`.
EDITABLE_FIELDS: frozenset[str] = frozenset(
    {
        "title",
        "specialty",
        "institution",
        "bio",
        "photo_url",
        "region",
        "display_order",
        "featured",
    }
)


def _derive_region_label(region: str | None) -> str | None:
    """Region label always follows the canonical taxonomy — never admin-set."""
    if region is None:
        return None
    return kol_regions.label_for(region)


def apply_kol_field_update(
    kol: KOL,
    updates: dict[str, Any],
    *,
    source: Literal["admin", "sync"],
) -> list[str]:
    """Apply `updates` to `kol`, respecting curated-field locks.

    Returns the list of field names that were actually modified — useful for
    logging and cache-clear scope decisions.
    """
    curated: set[str] = set(kol.curated_fields or [])
    changed: list[str] = []

    for field, value in updates.items():
        if field not in EDITABLE_FIELDS:
            continue

        if source == "sync" and field in curated:
            # Admin edit takes priority — skip sync overwrite.
            continue

        current = getattr(kol, field, None)
        if current == value:
            continue

        setattr(kol, field, value)
        changed.append(field)

        if field == "region":
            kol.region_label = _derive_region_label(value)

        if source == "admin":
            curated.add(field)

    if source == "admin" and changed:
        # Replace the list wholesale — SQLAlchemy JSONB in-place mutation is
        # not tracked reliably.
        kol.curated_fields = sorted(curated)

    return changed


def curated_lock_status(kol: KOL) -> dict[str, bool]:
    """Debug helper: `{field: is_curated}` for every editable field."""
    curated = set(kol.curated_fields or [])
    return {field: (field in curated) for field in EDITABLE_FIELDS}


def uncurate_fields(kol: KOL, fields: Iterable[str]) -> None:
    """Admin-facing 'release lock' operation. Removes fields from curated set
    so future sync writes may overwrite them again. Field values are unchanged.
    """
    curated = set(kol.curated_fields or [])
    to_remove = {f for f in fields if f in EDITABLE_FIELDS}
    if not (curated & to_remove):
        return
    kol.curated_fields = sorted(curated - to_remove)
