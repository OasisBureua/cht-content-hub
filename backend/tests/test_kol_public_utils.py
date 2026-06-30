"""Tests for utils.kol_public."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from models.kol import KOL
from utils.kol_public import build_kol_slug_map, kol_slug, kol_to_public


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Dr. Jason Mouabbi", "mouabbi"),
        ("Dr Virginia Kaklamani, MD", "kaklamani"),
        ("Dr Smith", "smith"),
        ("", ""),
        ("Dr. Jean-Paul Sartre", "sartre"),
    ],
)
def test_kol_slug(name: str, expected: str):
    assert kol_slug(name) == expected


@pytest.mark.asyncio
async def test_build_kol_slug_map_deduplicates():
    kols = [
        KOL(id="kol-jane", name="Dr. Jane Smith"),
        KOL(id="kol-john", name="Dr. John Smith"),
    ]
    slugs = await build_kol_slug_map(kols)
    assert len(slugs) == 2
    assert slugs["kol-jane"] == "smith"
    assert slugs["kol-john"] == "smith-2"


def test_kol_to_public_marks_new_kol():
    kol = KOL(
        id="kol-1",
        name="Dr. Jane Smith",
        region="california",
        institution="UCSF",
    )
    recent = datetime.now(timezone.utc) - timedelta(days=10)
    public = kol_to_public(kol, slug="smith", shoot_count=2, first_appeared_at=recent)
    assert public.slug == "smith"
    assert public.is_new is True
    assert public.region_label == "California"
    assert public.shoot_count == 2


def test_kol_to_public_marks_old_kol():
    kol = KOL(id="kol-2", name="Dr. Jane Smith", region="california")
    old = datetime.now(timezone.utc) - timedelta(days=120)
    public = kol_to_public(kol, slug="smith", shoot_count=0, first_appeared_at=old)
    assert public.is_new is False
