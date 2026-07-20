"""Tests for tagger observability (SCRUM-78)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from jobs.playlist_doctor_tagger import TagDiff, TagRunStats
from jobs.tagger_observability import record_run
from models.tagger_observability import TagDiffRow, TaggerRun
from sqlalchemy import select
from tests.conftest import api_headers


def _sample_stats(clips_changed: int = 2, posts_changed: int = 1) -> TagRunStats:
    stats = TagRunStats()
    stats.shoots_processed = 3
    stats.shoots_doctors_corrected = 1
    stats.clips_touched = clips_changed
    stats.clips_changed = clips_changed
    stats.posts_touched = posts_changed
    stats.posts_changed = posts_changed
    stats.playlists_orphaned_404 = ["PL_dead"]
    stats.api_errors = []
    return stats


def _sample_diff(entity_type: str = "clip") -> TagDiff:
    return TagDiff(
        entity_type=entity_type,
        entity_id="clip-1",
        provider_post_id=None,
        title="A clip",
        before=["drug:t-dxd"],
        after=["drug:t-dxd", "doctor:Traina"],
        shoot_id="shoot-1",
        shoot_name="Traina shoot",
    )


@pytest.mark.asyncio
async def test_record_run_persists_run_and_diffs(db_session: AsyncSession):
    started = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    finished = datetime(2026, 7, 20, 12, 5, tzinfo=timezone.utc)

    recorded = await record_run(
        db_session,
        _sample_stats(),
        [_sample_diff("clip"), _sample_diff("post")],
        started_at=started,
        finished_at=finished,
        mode="union",
        emit_cloudwatch=False,
    )

    run = await db_session.get(TaggerRun, recorded.run_id)
    assert run is not None
    assert run.mode == "union"
    assert run.clips_changed == 2
    assert run.posts_changed == 1
    assert run.orphaned_404_count == 1

    diffs = list(
        (
            await db_session.execute(
                select(TagDiffRow).where(TagDiffRow.run_id == recorded.run_id)
            )
        ).scalars()
    )
    assert len(diffs) == 2
    assert {d.entity_type for d in diffs} == {"clip", "post"}


@pytest.mark.asyncio
async def test_cloudwatch_emitter_noops_without_aws_region(
    db_session: AsyncSession, monkeypatch
):
    """Silent no-op when AWS_REGION isn't set — record still persists cleanly."""
    monkeypatch.delenv("AWS_REGION", raising=False)
    started = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)

    await record_run(
        db_session,
        _sample_stats(),
        [],
        started_at=started,
        emit_cloudwatch=True,  # Would try to emit, but no AWS_REGION means no-op.
    )
    # No exception ⇒ pass.


@pytest.mark.asyncio
async def test_admin_runs_endpoint(client: AsyncClient, db_session: AsyncSession):
    for i in range(3):
        await record_run(
            db_session,
            _sample_stats(),
            [],
            started_at=datetime(2026, 7, 20, 12, i, tzinfo=timezone.utc),
            finished_at=datetime(2026, 7, 20, 12, i + 1, tzinfo=timezone.utc),
            emit_cloudwatch=False,
        )
    await db_session.commit()

    r = await client.get("/api/admin/tagger/runs", headers=api_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3
    # Most recent first
    assert body["items"][0]["finished_at"] > body["items"][-1]["finished_at"]


@pytest.mark.asyncio
async def test_admin_runs_requires_api_key(client: AsyncClient):
    r = await client.get("/api/admin/tagger/runs")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_admin_diffs_endpoint_and_entity_filter(
    client: AsyncClient, db_session: AsyncSession
):
    await record_run(
        db_session,
        _sample_stats(),
        [_sample_diff("clip"), _sample_diff("post"), _sample_diff("shoot")],
        started_at=datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc),
        emit_cloudwatch=False,
    )
    await db_session.commit()

    r_all = await client.get("/api/admin/tagger/diffs", headers=api_headers())
    assert r_all.status_code == 200
    assert r_all.json()["total"] == 3

    r_clip = await client.get(
        "/api/admin/tagger/diffs?entity_type=clip", headers=api_headers()
    )
    assert r_clip.status_code == 200
    body = r_clip.json()
    assert body["total"] == 1
    assert body["items"][0]["entity_type"] == "clip"


@pytest.mark.asyncio
async def test_admin_diffs_rejects_bad_entity_type(client: AsyncClient):
    r = await client.get(
        "/api/admin/tagger/diffs?entity_type=bogus", headers=api_headers()
    )
    assert r.status_code == 422
