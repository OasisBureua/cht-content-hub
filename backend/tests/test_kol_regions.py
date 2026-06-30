"""Tests for services.kol_regions."""

from __future__ import annotations

from services.kol_regions import (
    REGIONS,
    infer_region_from_institution,
    label_for,
)


def test_regions_are_unique():
    slugs = [r["slug"] for r in REGIONS]
    assert len(slugs) == len(set(slugs))


def test_label_for_known_region():
    assert label_for("california") == "California"
    assert label_for("texas") == "Texas"


def test_label_for_unknown_region():
    assert label_for("unknown") is None
    assert label_for(None) is None


def test_infer_region_exact_match():
    assert infer_region_from_institution("MD Anderson") == "texas"
    assert infer_region_from_institution("UCSF") == "california"


def test_infer_region_substring_match():
    assert infer_region_from_institution("MSK Breast Service") == "ny-northeast"


def test_infer_region_no_match():
    assert infer_region_from_institution("Unknown Hospital") is None
    assert infer_region_from_institution(None) is None
