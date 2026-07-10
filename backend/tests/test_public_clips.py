"""Integration tests for /api/public/clips endpoint.

Verifies auth, empty state, filters (q/tag/doctor/platform), sort, dedup by shoot,
per_shoot_cap, engagement aggregation from posts, YouTube URL construction, and
the X-Total-Count header. Uses the same in-memory SQLite pattern as playlist tests.
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
async def seeded_clips(db_session: AsyncSession):
    """Seed 4 shoots + 5 clips (3 official, 2 branded) + posts w/ engagement stats."""
    shoot_a = Shoot(id="s-a", name="Shoot A", shoot_date=_dt(2026, 6, 1))
    shoot_b = Shoot(id="s-b", name="Shoot B", shoot_date=_dt(2026, 6, 10))
    shoot_c = Shoot(id="s-c", name="Shoot C", shoot_date=None)
    db_session.add_all([shoot_a, shoot_b, shoot_c])
    await db_session.flush()

    # 3 official clips — two share shoot_a, one has shoot_b
    c1 = Clip(
        id="c1",
        title="HER2 update",
        description="Latest",
        tags=["biomarker:HER2+", "drug:T-DXd", "doctor:Alice Smith"],
        channel="chm-official",
        platform="youtube",
        is_short=False,
        shoot_id="s-a",
        duration_seconds=600,
    )
    c2 = Clip(
        id="c2",
        title="HER2 short",
        description="Cut",
        tags=["biomarker:HER2+", "doctor:Alice Smith"],
        channel="chm-official",
        platform="youtube",
        is_short=True,
        shoot_id="s-a",
        duration_seconds=60,
    )
    c3 = Clip(
        id="c3",
        title="CNS trial",
        description="Trial results",
        tags=["biomarker:HER2+", "topic:CNS"],
        channel="chm-official",
        platform="podcast",
        shoot_id="s-b",
        duration_seconds=1800,
    )
    # 1 branded (should never appear in results)
    c4 = Clip(
        id="c4",
        title="Branded AZ",
        tags=["biomarker:HER2+"],
        channel="branded-az",
        shoot_id="s-c",
    )
    # 1 clip with no shoot
    c5 = Clip(
        id="c5",
        title="Orphan",
        tags=["topic:CNS", "doctor:Bob Jones"],
        channel="chm-official",
        platform="youtube",
        shoot_id=None,
    )
    db_session.add_all([c1, c2, c3, c4, c5])
    await db_session.flush()

    posts = [
        Post(
            id="p1",
            clip_id="c1",
            platform="youtube",
            provider_post_id="yt_c1",
            posted_at=_dt(2026, 6, 5),
            thumbnail_url="https://img/c1.jpg",
            view_count=1000,
            like_count=100,
            comment_count=10,
        ),
        Post(
            id="p2",
            clip_id="c2",
            platform="youtube",
            provider_post_id="yt_c2",
            posted_at=_dt(2026, 6, 6),
            thumbnail_url="https://img/c2.jpg",
            view_count=500,
            like_count=50,
            comment_count=5,
        ),
        Post(
            id="p3",
            clip_id="c3",
            platform="youtube",
            provider_post_id="yt_c3",
            posted_at=_dt(2026, 6, 15),
            thumbnail_url="https://img/c3.jpg",
            view_count=2000,
            like_count=200,
            comment_count=20,
        ),
        Post(
            id="p5",
            clip_id="c5",
            platform="youtube",
            provider_post_id="yt_c5",
            posted_at=_dt(2026, 6, 20),
            thumbnail_url="https://img/c5.jpg",
            view_count=300,
            like_count=30,
            comment_count=3,
        ),
    ]
    db_session.add_all(posts)
    await db_session.commit()
    return {"shoots": [shoot_a, shoot_b, shoot_c], "clips": [c1, c2, c3, c4, c5]}


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clips_requires_api_key(http_client: AsyncClient):
    response = await http_client.get("/api/public/clips")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_clips_rejects_invalid_api_key(http_client: AsyncClient):
    response = await http_client.get(
        "/api/public/clips",
        headers={"X-API-Key": "wrong"},
    )
    assert response.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# Baseline: empty state + basic listing
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clips_empty_when_no_data(client: AsyncClient):
    response = await client.get("/api/public/clips", headers=api_headers())
    assert response.status_code == 200
    assert response.json() == []
    assert response.headers.get("X-Total-Count") == "0"


@pytest.mark.asyncio
async def test_clips_returns_only_official_channel(
    client: AsyncClient, seeded_clips
):
    response = await client.get("/api/public/clips", headers=api_headers())
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    assert ids == {"c1", "c2", "c3", "c5"}  # c4 branded — excluded


@pytest.mark.asyncio
async def test_clips_engagement_aggregated_from_posts(
    client: AsyncClient, seeded_clips
):
    response = await client.get("/api/public/clips", headers=api_headers())
    items = {item["id"]: item for item in response.json()}
    assert items["c1"]["view_count"] == 1000
    assert items["c1"]["like_count"] == 100
    assert items["c1"]["comment_count"] == 10
    assert items["c1"]["youtube_url"] == "https://www.youtube.com/watch?v=yt_c1"
    assert items["c2"]["youtube_url"] == "https://www.youtube.com/shorts/yt_c2"


@pytest.mark.asyncio
async def test_clips_doctors_extracted_from_tags(
    client: AsyncClient, seeded_clips
):
    response = await client.get("/api/public/clips", headers=api_headers())
    by_id = {item["id"]: item for item in response.json()}
    assert by_id["c1"]["doctors"] == ["Alice Smith"]
    assert by_id["c3"]["doctors"] == []


# ─────────────────────────────────────────────────────────────────────────────
# Filters
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clips_tag_filter_and_logic(client: AsyncClient, seeded_clips):
    # c1 has both HER2+ AND T-DXd; c2 has HER2+ only
    response = await client.get(
        "/api/public/clips?tag=biomarker:HER2%2B,drug:T-DXd",
        headers=api_headers(),
    )
    ids = [item["id"] for item in response.json()]
    assert ids == ["c1"]


@pytest.mark.asyncio
async def test_clips_doctor_filter(client: AsyncClient, seeded_clips):
    response = await client.get(
        "/api/public/clips?doctor=Alice Smith",
        headers=api_headers(),
    )
    ids = {item["id"] for item in response.json()}
    assert ids == {"c1", "c2"}


@pytest.mark.asyncio
async def test_clips_platform_filter(client: AsyncClient, seeded_clips):
    response = await client.get(
        "/api/public/clips?platform=podcast",
        headers=api_headers(),
    )
    ids = {item["id"] for item in response.json()}
    assert ids == {"c3"}


@pytest.mark.asyncio
async def test_clips_q_search(client: AsyncClient, seeded_clips):
    response = await client.get(
        "/api/public/clips?q=CNS",
        headers=api_headers(),
    )
    ids = {item["id"] for item in response.json()}
    # c3 matches via title "CNS trial" + description "Trial results".
    # c5 has "topic:CNS" as a tag, but the ilike search is on title/description only.
    # Postgres would also probe exact `tags.any('CNS')` — no clip has bare "CNS".
    assert ids == {"c3"}


# ─────────────────────────────────────────────────────────────────────────────
# Sort
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clips_sort_by_views_default(client: AsyncClient, seeded_clips):
    response = await client.get("/api/public/clips", headers=api_headers())
    ids = [item["id"] for item in response.json()]
    # By views desc: c3 (2000) > c1 (1000) > c2 (500) > c5 (300)
    assert ids == ["c3", "c1", "c2", "c5"]


@pytest.mark.asyncio
async def test_clips_sort_by_recent(client: AsyncClient, seeded_clips):
    response = await client.get(
        "/api/public/clips?sort_by=recent", headers=api_headers()
    )
    ids = [item["id"] for item in response.json()]
    # posted_at desc: c5 (6/20) > c3 (6/15) > c2 (6/6) > c1 (6/5)
    assert ids == ["c5", "c3", "c2", "c1"]


# ─────────────────────────────────────────────────────────────────────────────
# Dedup + per-shoot-cap
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clips_dedup_by_shoot_keeps_youtube(
    client: AsyncClient, seeded_clips
):
    # c1+c2 share s-a; both are youtube, so first (best sort rank) wins per shoot.
    # c3 shoot s-b, c5 no shoot.
    response = await client.get(
        "/api/public/clips?dedup_by=shoot", headers=api_headers()
    )
    ids = [item["id"] for item in response.json()]
    # Sort=views default: c3 (2000) first, then c1 (from shoot s-a, best of c1+c2),
    # then c5 (no shoot passes through).
    assert "c3" in ids
    assert "c5" in ids
    # Only one of c1 or c2 (both youtube, so top-view within group wins → c1)
    assert ("c1" in ids) ^ ("c2" in ids)
    assert "c1" in ids  # c1 has more views


@pytest.mark.asyncio
async def test_clips_per_shoot_cap_limits_group(
    client: AsyncClient, seeded_clips
):
    response = await client.get(
        "/api/public/clips?per_shoot_cap=1", headers=api_headers()
    )
    ids = [item["id"] for item in response.json()]
    # Both c1 and c2 belong to shoot s-a; only the first (higher views = c1) kept.
    # c3, c5 always kept.
    assert "c3" in ids
    assert "c5" in ids
    assert "c1" in ids
    assert "c2" not in ids


# ─────────────────────────────────────────────────────────────────────────────
# Pagination + X-Total-Count
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clips_pagination_and_total_count(
    client: AsyncClient, seeded_clips
):
    response = await client.get(
        "/api/public/clips?limit=2&offset=0", headers=api_headers()
    )
    body = response.json()
    assert len(body) == 2
    assert response.headers["X-Total-Count"] == "4"

    response = await client.get(
        "/api/public/clips?limit=2&offset=2", headers=api_headers()
    )
    assert len(response.json()) == 2
    assert response.headers["X-Total-Count"] == "4"


@pytest.mark.asyncio
async def test_clips_shoot_name_populated(client: AsyncClient, seeded_clips):
    response = await client.get("/api/public/clips", headers=api_headers())
    by_id = {item["id"]: item for item in response.json()}
    assert by_id["c1"]["shoot_name"] == "Shoot A"
    assert by_id["c3"]["shoot_name"] == "Shoot B"
    assert by_id["c5"]["shoot_name"] is None
