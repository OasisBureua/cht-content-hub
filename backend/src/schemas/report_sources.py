"""CPR-44 — report-packet source keys shared with Platform ReportsPanel.

Keep this list in sync with:
  cht-platform-tool/frontend/.../ReportsPanel.tsx ``REPORT_SOURCES``

``CampaignPlatformData.platform`` still uses ``Platform`` enum values
(``survey``, ``livestream``, …). Report toggles use the keys below;
``survey`` uploads map to the ``surveys`` toggle. ``livestream`` is not
a report source until Q&A capture exists (CPR-33).
"""

from __future__ import annotations

# Canonical keys the UI may send on report-packet ``sources``.
REPORT_SOURCE_KEYS: tuple[str, ...] = (
    "hubspot",
    "linkedin",
    "meta",
    "youtube",
    "sessions",
    "attendance",
    "kols",
    "surveys",
)

# Warehouse / platform row name → report toggle key.
_SOURCE_ALIASES: dict[str, str] = {
    "survey": "surveys",
}


def canonical_report_source(name: str) -> str:
    """Map stored platform names onto report toggle keys."""
    key = (name or "").strip()
    return _SOURCE_ALIASES.get(key, key)


def normalize_requested_sources(sources: list[str] | None) -> set[str] | None:
    """None / omitted / empty list ⇒ every section.

    A non-empty request that only contains dropped keys (e.g. ``livestream``)
    yields an empty set — meaning no sections — not “all sources”.

    Pre-CPR-44 jobs stored ``livestream`` with ``sessions`` and did not have
    separate ``attendance`` / ``kols`` toggles. Seeing ``livestream`` in the
    raw list restores that coupling so regenerate does not drop attendees/KOLs.
    New UI never sends ``livestream``, so independent toggles stay intact.
    """
    if not sources:
        return None
    out: set[str] = set()
    saw_livestream = False
    for item in sources:
        if not item or not str(item).strip():
            continue
        raw = str(item).strip()
        if raw == "livestream":
            saw_livestream = True
            continue
        out.add(canonical_report_source(raw))
    if saw_livestream and "sessions" in out:
        out.add("attendance")
        out.add("kols")
    return out


def wants_source(requested: set[str] | None, name: str) -> bool:
    """Whether ``name`` (or its alias) is included in the request.

    ``livestream`` is never a report source (CPR-33), even when ``sources``
    is omitted (all-sections mode).
    """
    key = canonical_report_source(name)
    if key == "livestream" or (name or "").strip() == "livestream":
        return False
    if requested is None:
        return True
    return key in requested
