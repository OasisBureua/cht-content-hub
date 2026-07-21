"""Persist tagger runs + emit CloudWatch metrics (SCRUM-78).

The tagger returns (TagRunStats, list[TagDiff]) in memory only. This
recorder writes them to the tagger_runs + tag_diffs tables so the admin
UI can show recent activity and CloudWatch alarms can page on
regressions ('0 propagations for 24h' → likely the tagger is broken).

Called by the Lambda / cron entrypoint AFTER tag_clips_from_playlists
returns. Kept separate from the tagger itself so unit tests of the
merge logic don't drag in DB or boto3.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from jobs.playlist_doctor_tagger import TagDiff, TagRunStats
from models.tagger_observability import TagDiffRow, TaggerRun

logger = logging.getLogger(__name__)

CLOUDWATCH_NAMESPACE = "CHM/ContentHub/Tagger"


@dataclass
class RecordedRun:
    run_id: str
    started_at: datetime
    finished_at: datetime


async def record_run(
    db: AsyncSession,
    stats: TagRunStats,
    diffs: list[TagDiff],
    *,
    started_at: datetime,
    finished_at: datetime | None = None,
    mode: str = "union",
    dry_run: bool = False,
    emit_cloudwatch: bool = True,
) -> RecordedRun:
    """Persist one tagger run + its TagDiffs; optionally emit CloudWatch metrics.

    Idempotent per-run via a new UUID. Caller commits after this returns.
    """
    fin = finished_at or datetime.now(timezone.utc)
    run_id = str(uuid.uuid4())

    run = TaggerRun(
        id=run_id,
        started_at=started_at,
        finished_at=fin,
        mode=mode,
        dry_run=dry_run,
        shoots_processed=stats.shoots_processed,
        shoots_doctors_corrected=stats.shoots_doctors_corrected,
        clips_changed=stats.clips_changed,
        posts_changed=stats.posts_changed,
        clips_curator_locked_skipped=stats.clips_curator_locked_skipped,
        posts_curator_locked_skipped=stats.posts_curator_locked_skipped,
        orphaned_404_count=len(stats.playlists_orphaned_404),
        api_error_count=len(stats.api_errors),
        clip_post_skipped_models_missing=stats.clip_post_skipped_models_missing,
    )
    db.add(run)

    for d in diffs:
        db.add(
            TagDiffRow(
                id=str(uuid.uuid4()),
                run_id=run_id,
                entity_type=d.entity_type,
                entity_id=d.entity_id,
                shoot_id=d.shoot_id,
                shoot_name=d.shoot_name,
                provider_post_id=d.provider_post_id,
                title=d.title,
                before_tags=list(d.before or []),
                after_tags=list(d.after or []),
            )
        )
    await db.flush()

    if emit_cloudwatch:
        _emit_cloudwatch_metrics(stats)

    logger.info(
        "Tagger run persisted: id=%s clips_changed=%d posts_changed=%d api_errors=%d",
        run_id, stats.clips_changed, stats.posts_changed, len(stats.api_errors),
    )
    return RecordedRun(run_id=run_id, started_at=started_at, finished_at=fin)


def _emit_cloudwatch_metrics(stats: TagRunStats) -> None:
    """Best-effort CloudWatch put_metric_data. Silently no-ops without boto3
    or AWS creds — the DB record is the source of truth; metrics are for
    alarms only.
    """
    try:
        import boto3
    except ImportError:
        return
    if not os.environ.get("AWS_REGION"):
        return
    try:
        client = boto3.client("cloudwatch", region_name=os.environ["AWS_REGION"])
        client.put_metric_data(
            Namespace=CLOUDWATCH_NAMESPACE,
            MetricData=[
                {"MetricName": "TaggerRuns", "Value": 1, "Unit": "Count"},
                {"MetricName": "ClipsChanged", "Value": stats.clips_changed, "Unit": "Count"},
                {"MetricName": "PostsChanged", "Value": stats.posts_changed, "Unit": "Count"},
                {"MetricName": "ApiErrors", "Value": len(stats.api_errors), "Unit": "Count"},
                {"MetricName": "OrphanedPlaylists", "Value": len(stats.playlists_orphaned_404), "Unit": "Count"},
                {
                    "MetricName": "TotalPropagations",
                    "Value": stats.clips_changed + stats.posts_changed,
                    "Unit": "Count",
                },
            ],
        )
    except Exception as exc:
        logger.warning("CloudWatch put_metric_data failed: %s", exc)
