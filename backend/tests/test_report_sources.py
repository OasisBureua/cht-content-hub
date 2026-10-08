"""CPR-44 — shared report source key helpers."""

from schemas.report_sources import (
    REPORT_SOURCE_KEYS,
    canonical_report_source,
    normalize_requested_sources,
    wants_source,
)


def test_report_source_keys_stable():
    assert REPORT_SOURCE_KEYS == (
        "hubspot",
        "linkedin",
        "meta",
        "youtube",
        "sessions",
        "attendance",
        "kols",
        "surveys",
    )


def test_survey_alias_and_livestream_dropped():
    assert canonical_report_source("survey") == "surveys"
    assert canonical_report_source("surveys") == "surveys"
    requested = normalize_requested_sources(["survey", "sessions"])
    assert requested == {"surveys", "sessions"}
    assert wants_source(requested, "survey") is True
    assert wants_source(requested, "surveys") is True
    # livestream is never a report source, including all-sections mode
    assert wants_source(None, "livestream") is False
    assert wants_source(requested, "livestream") is False
    # livestream-only must not expand to “all sources”
    assert normalize_requested_sources(["livestream"]) == set()
    assert wants_source(set(), "sessions") is False
    assert normalize_requested_sources([]) is None
    assert normalize_requested_sources(None) is None


def test_legacy_livestream_restores_attendance_and_kols_with_sessions():
    """Pre-CPR-44 Select-all stored livestream; regenerate must keep attendees/KOLs."""
    legacy = [
        "hubspot",
        "linkedin",
        "meta",
        "youtube",
        "livestream",
        "sessions",
        "surveys",
    ]
    requested = normalize_requested_sources(legacy)
    assert requested == {
        "hubspot",
        "linkedin",
        "meta",
        "youtube",
        "sessions",
        "attendance",
        "kols",
        "surveys",
    }
    # New UI never sends livestream — sessions-only stays sessions-only.
    assert normalize_requested_sources(["sessions"]) == {"sessions"}
