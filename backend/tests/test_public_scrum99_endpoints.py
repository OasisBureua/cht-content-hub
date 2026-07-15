"""Integration tests for SCRUM-99 Phase A endpoints.

Covers:
- GET /api/public/tags
- GET /api/public/doctors
- GET /api/public/transcripts/{shoot_id}
- GET /api/public/clips/{clip_id}

Uses same in-memory SQLite pattern as test_public_clips.py.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import API_KEY, api_headers
from models.clip import Clip
from models.post import Post
from models.shoot import Shoot


def _dt(y, m, d) -> datetime:
    return datetime(y, m, d, tzinfo=timezone.utc)


@pytest.fixture
async def seeded_catalog(db_session: AsyncSession):
    """Two shoots (one w/ transcript, one without) + three official clips + a branded clip."""
    shoot_transcribed = Shoot(
        id="s-1",
        name="Alice + Bob Roundtable",
        shoot_date=_dt(2026, 6, 1),
        diarized_transcript="Dr. Alice [00:00]:\nHello there.\n\nDr. Bob [00:10]:\nHi Alice.",
    )
    shoot_bare = Shoot(id="s-2", name="Bare Shoot", shoot_date=_dt(2026, 6, 10))
    db_session.add_all([shoot_transcribed, shoot_bare])
    await db_session.flush()

    c1 = Clip(
        id="official:youtube:abc123DEFgh",
        title="HER2 discussion",
        description="Deep dive",
        tags=["biomarker:HER2+", "drug:T-DXd", "doctor:alice-smith", "topic:cns"],
        channel="chm-official",
        platform="youtube",
        is_short=False,
        shoot_id="s-1",
        duration_seconds=600,
    )
    c2 = Clip(
        id="official:youtube:xyz789IJKlm",
        title="Trial update",
        description="Latest results",
        tags=["trial:DESTINY-08", "doctor:bob-jones", "stage:early"],
        channel="chm-official",
        platform="youtube",
        is_short=True,
        shoot_id="s-2",
        duration_seconds=90,
    )
    c3 = Clip(
        id="official:youtube:untagged1",
        title="Untagged bare",
        description="No namespaces",
        tags=["chemotherapy", "brand:CHM"],
        channel="chm-official",
        platform="youtube",
        is_short=False,
        shoot_id=None,
        duration_seconds=120,
    )
    c_branded = Clip(
        id="branded:youtube:excludeme",
        title="Branded contractor content",
        tags=["biomarker:HER2-low", "doctor:excluded-doc"],
        channel="branded",
        platform="youtube",
        is_short=False,
    )
    db_session.add_all([c1, c2, c3, c_branded])
    await db_session.flush()

    posts = [
        Post(
            id="p-1",
            clip_id="official:youtube:abc123DEFgh",
            platform="youtube",
            provider_post_id="abc123DEFgh",
            thumbnail_url="https://img.example.com/abc.jpg",
            view_count=1000,
            like_count=50,
            comment_count=5,
            posted_at=_dt(2026, 6, 2),
            tags=["biomarker:HER2+"],
        ),
        Post(
            id="p-2",
            clip_id="official:youtube:xyz789IJKlm",
            platform="youtube",
            provider_post_id="xyz789IJKlm",
            thumbnail_url="https://img.example.com/xyz.jpg",
            view_count=200,
            like_count=10,
            comment_count=0,
            posted_at=_dt(2026, 6, 11),
            tags=[],
        ),
    ]
    db_session.add_all(posts)
    await db_session.flush()
    return {"clips": [c1, c2, c3], "shoots": [shoot_transcribed, shoot_bare]}


# ---------------------------------------------------------------------------
# GET /api/public/tags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tags_requires_api_key(client: AsyncClient):
    r = await client.get("/api/public/tags")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_tags_returns_grouped_namespaces(
    client: AsyncClient, seeded_catalog
):
    r = await client.get("/api/public/tags", headers=api_headers())
    assert r.status_code == 200
    data = r.json()
    # Six namespaces the CHT VideosPage hardcodes must all be present.
    for ns in ("biomarker", "drug", "trial", "doctor", "topic", "brand"):
        assert ns in data, f"missing namespace {ns!r}"
    assert "biomarker:HER2+" in data["biomarker"]
    assert "drug:T-DXd" in data["drug"]
    assert "trial:DESTINY-08" in data["trial"]
    assert "doctor:alice-smith" in data["doctor"]
    assert "doctor:bob-jones" in data["doctor"]
    assert "topic:cns" in data["topic"]
    assert "brand:CHM" in data["brand"]
    # Bare (unprefixed) tags collapse into "other".
    assert "chemotherapy" in data["other"]
    # Branded-channel doctor tag must NOT appear.
    assert "doctor:excluded-doc" not in data.get("doctor", [])


@pytest.mark.asyncio
async def test_tags_sorted_within_namespace(client: AsyncClient, seeded_catalog):
    r = await client.get("/api/public/tags", headers=api_headers())
    doctors = r.json()["doctor"]
    assert doctors == sorted(doctors)


# ---------------------------------------------------------------------------
# GET /api/public/doctors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_doctors_requires_api_key(client: AsyncClient):
    r = await client.get("/api/public/doctors")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_doctors_returns_distinct_slugs(client: AsyncClient, seeded_catalog):
    r = await client.get("/api/public/doctors", headers=api_headers())
    assert r.status_code == 200
    slugs = [d["slug"] for d in r.json()]
    assert slugs == ["alice-smith", "bob-jones"]  # sorted, branded excluded


@pytest.mark.asyncio
async def test_doctors_empty_when_no_data(client: AsyncClient):
    r = await client.get("/api/public/doctors", headers=api_headers())
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# GET /api/public/transcripts/{shoot_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcript_requires_api_key(client: AsyncClient):
    r = await client.get("/api/public/transcripts/s-1")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_transcript_returns_diarized_text(client: AsyncClient, seeded_catalog):
    r = await client.get("/api/public/transcripts/s-1", headers=api_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["shoot_name"] == "Alice + Bob Roundtable"
    assert "Dr. Alice" in body["transcript"]
    assert "Dr. Bob" in body["transcript"]


@pytest.mark.asyncio
async def test_transcript_404_when_shoot_missing(client: AsyncClient, seeded_catalog):
    r = await client.get("/api/public/transcripts/does-not-exist", headers=api_headers())
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_transcript_404_when_shoot_has_no_transcript(
    client: AsyncClient, seeded_catalog
):
    r = await client.get("/api/public/transcripts/s-2", headers=api_headers())
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/public/clips/{clip_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clip_detail_requires_api_key(client: AsyncClient):
    r = await client.get("/api/public/clips/official:youtube:abc123DEFgh")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_clip_detail_returns_enriched_clip(
    client: AsyncClient, seeded_catalog
):
    r = await client.get(
        "/api/public/clips/official:youtube:abc123DEFgh", headers=api_headers()
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "official:youtube:abc123DEFgh"
    assert body["title"] == "HER2 discussion"
    assert body["view_count"] == 1000
    assert body["like_count"] == 50
    assert body["comment_count"] == 5
    assert body["youtube_url"] == "https://www.youtube.com/watch?v=abc123DEFgh"
    assert body["thumbnail_url"] == "https://img.example.com/abc.jpg"
    assert body["shoot_id"] == "s-1"
    assert body["shoot_name"] == "Alice + Bob Roundtable"
    assert "alice-smith" in body["doctors"]


@pytest.mark.asyncio
async def test_clip_detail_shorts_url_format(client: AsyncClient, seeded_catalog):
    r = await client.get(
        "/api/public/clips/official:youtube:xyz789IJKlm", headers=api_headers()
    )
    assert r.status_code == 200
    assert r.json()["youtube_url"] == "https://www.youtube.com/shorts/xyz789IJKlm"


@pytest.mark.asyncio
async def test_clip_detail_404_when_missing(client: AsyncClient, seeded_catalog):
    r = await client.get(
        "/api/public/clips/official:youtube:notreal", headers=api_headers()
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_clip_detail_404_when_branded_channel(
    client: AsyncClient, seeded_catalog
):
    r = await client.get(
        "/api/public/clips/branded:youtube:excludeme", headers=api_headers()
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_clip_detail_zero_stats_when_no_posts(
    client: AsyncClient, seeded_catalog
):
    r = await client.get(
        "/api/public/clips/official:youtube:untagged1", headers=api_headers()
    )
    assert r.status_code == 200
    body = r.json()
    assert body["view_count"] == 0
    assert body["like_count"] == 0
    assert body["comment_count"] == 0
    assert body["shoot_id"] is None
    assert body["shoot_name"] is None
