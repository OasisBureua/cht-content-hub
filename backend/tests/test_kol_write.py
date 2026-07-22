"""SCRUM-61: verify curated-field guard on the KOL write helper.

kol_write.apply_kol_field_update is the single write point for both admin
PATCH and future enrichment sync jobs. This suite locks the "admin edits
survive sync overwrites" invariant.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from models.kol import KOL
from services import kol_write
from utils.kol_public import kol_slug


@pytest.mark.asyncio
async def test_admin_update_marks_curated(db_session: AsyncSession):
    kol = KOL(slug=kol_slug("Dr. Curate A"), name="Dr. Curate A")
    db_session.add(kol)
    await db_session.flush()

    changed = kol_write.apply_kol_field_update(
        kol, {"bio": "First bio", "title": "MD"}, source="admin"
    )

    assert set(changed) == {"bio", "title"}
    assert kol.bio == "First bio"
    assert kol.title == "MD"
    assert set(kol.curated_fields) == {"bio", "title"}


@pytest.mark.asyncio
async def test_sync_respects_admin_lock(db_session: AsyncSession):
    kol = KOL(
        slug=kol_slug("Dr. Locked"),
        name="Dr. Locked",
        bio="admin-authored bio",
        curated_fields=["bio"],
    )
    db_session.add(kol)
    await db_session.flush()

    changed = kol_write.apply_kol_field_update(
        kol, {"bio": "sync-would-overwrite"}, source="sync"
    )

    assert changed == []
    assert kol.bio == "admin-authored bio"


@pytest.mark.asyncio
async def test_sync_writes_uncurated_field(db_session: AsyncSession):
    kol = KOL(slug=kol_slug("Dr. Sync"), name="Dr. Sync", curated_fields=[])
    db_session.add(kol)
    await db_session.flush()

    changed = kol_write.apply_kol_field_update(
        kol, {"institution": "MD Anderson"}, source="sync"
    )

    assert changed == ["institution"]
    assert kol.institution == "MD Anderson"
    # sync writes must NOT mark the field curated
    assert kol.curated_fields == []


@pytest.mark.asyncio
async def test_editable_fields_allowlist_blocks_unknown_keys(db_session: AsyncSession):
    kol = KOL(slug=kol_slug("Dr. Fence"), name="Dr. Fence")
    db_session.add(kol)
    await db_session.flush()

    changed = kol_write.apply_kol_field_update(
        kol,
        {
            "bio": "ok",
            "hcp_match_status": "manually_locked",  # not editable via this path
            "name": "SHOULD NOT CHANGE",  # name isn't editable via admin API
        },
        source="admin",
    )

    assert changed == ["bio"]
    assert kol.name == "Dr. Fence"
    assert kol.hcp_match_status == "unresolved"


@pytest.mark.asyncio
async def test_region_update_derives_region_label(db_session: AsyncSession):
    kol = KOL(slug=kol_slug("Dr. Region"), name="Dr. Region")
    db_session.add(kol)
    await db_session.flush()

    kol_write.apply_kol_field_update(kol, {"region": "texas"}, source="admin")

    assert kol.region == "texas"
    # kol_regions.label_for("texas") canonical taxonomy
    assert kol.region_label is not None


@pytest.mark.asyncio
async def test_no_op_when_value_unchanged(db_session: AsyncSession):
    kol = KOL(slug=kol_slug("Dr. Same"), name="Dr. Same", bio="unchanged")
    db_session.add(kol)
    await db_session.flush()

    changed = kol_write.apply_kol_field_update(
        kol, {"bio": "unchanged"}, source="admin"
    )

    assert changed == []
    assert kol.curated_fields == []  # no change → no curation event


@pytest.mark.asyncio
async def test_uncurate_releases_lock(db_session: AsyncSession):
    kol = KOL(
        slug=kol_slug("Dr. Unlock"),
        name="Dr. Unlock",
        bio="admin-authored",
        curated_fields=["bio", "title"],
    )
    db_session.add(kol)
    await db_session.flush()

    kol_write.uncurate_fields(kol, ["bio"])

    assert set(kol.curated_fields) == {"title"}
    assert kol.bio == "admin-authored"  # value unchanged, only lock released
