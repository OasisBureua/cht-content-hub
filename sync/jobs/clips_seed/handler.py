"""clips_seed - one-shot Lambda that restores mediahub prod clip data into contenthub RDS.

Triggered manually (no schedule, no SQS). Reads a pg_dump SQL file from S3
(generated with `pg_dump --data-only --column-inserts --disable-triggers` against
mediahub prod - see `.claude/plans/clip-data-seed.md` for the exact command)
and applies it to the contenthub RDS instance in a single transaction.

Design:
- Idempotent: skips the restore if `clips` already has >= SKIP_THRESHOLD rows.
  The dump is meant to be a one-time bootstrap; re-invocations return status=skipped.
- Transactional: entire dump runs inside `BEGIN ... COMMIT`. If any statement
  fails, the whole thing rolls back - the DB stays in the pre-seed state.
- psql-metacommand-safe: strips `\\restrict`/`\\unrestrict` lines (pg_dump 16+
  emits these; they are psql-only, asyncpg cannot parse them).
- --disable-triggers is baked into the dump so FK ordering doesn't matter,
  but the standard order (shoots, clips, posts) is what pg_dump produces anyway.

Invocation:
    aws lambda invoke \\
      --function-name contenthub-dev-sync-clips-seed \\
      --payload '{"bucket":"contenthub-dev-assets","key":"seeds/mediahub-clips-posts-2026-07-10.sql"}' \\
      /tmp/resp.json && cat /tmp/resp.json
"""

from __future__ import annotations

import logging
import os
from typing import Any

import boto3

from shared.runtime import configure_logging, install_paths, run_async

log = logging.getLogger(__name__)

# When the payload doesn't specify - matches the seed we upload during initial rollout.
_DEFAULT_BUCKET_ENV = "CLIPS_SEED_BUCKET"
_DEFAULT_KEY_ENV = "CLIPS_SEED_KEY"

# If clips already has >= this many rows, treat the DB as already-seeded and skip.
# Chosen well below the ~3.1k mediahub prod count so a partial seed still triggers
# a re-run (the transaction guarantees "all or nothing", so a partial state
# shouldn't exist - but the guard is cheap safety).
_SKIP_THRESHOLD = 100


def _strip_psql_metacommands(sql: str) -> str:
    """Remove psql-specific `\\restrict`/`\\unrestrict` lines that pg_dump 16 emits.

    asyncpg speaks the wire protocol directly, not psql, so backslash commands
    are syntax errors. Every other statement (INSERTs, SETs, SELECT setval)
    is standard SQL and passes through untouched.
    """
    kept = []
    for line in sql.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("\\restrict") or stripped.startswith("\\unrestrict"):
            continue
        kept.append(line)
    return "".join(kept)


async def _restore(bucket: str, key: str) -> dict[str, Any]:
    """Fetch the SQL dump from S3 and apply it to contenthub RDS."""
    import asyncpg

    database_url = os.environ["DATABASE_URL"]
    # asyncpg wants postgres://, not postgresql+asyncpg://
    for prefix in ("postgresql+asyncpg://", "postgresql://"):
        if database_url.startswith(prefix):
            database_url = "postgres://" + database_url[len(prefix):]
            break

    s3 = boto3.client("s3")
    log.info("Fetching seed SQL from s3://%s/%s", bucket, key)
    obj = s3.get_object(Bucket=bucket, Key=key)
    sql_bytes = obj["Body"].read()
    sql = sql_bytes.decode("utf-8")
    sql = _strip_psql_metacommands(sql)
    log.info("Fetched %d bytes of SQL", len(sql_bytes))

    conn = await asyncpg.connect(database_url)
    try:
        existing = await conn.fetchval("SELECT COUNT(*) FROM clips")
        if existing >= _SKIP_THRESHOLD:
            log.info(
                "Skipping seed - clips already has %d rows (threshold %d)",
                existing,
                _SKIP_THRESHOLD,
            )
            return {
                "status": "skipped",
                "reason": "already_seeded",
                "existing_clips": existing,
            }

        log.info("Applying seed (existing clips: %d)", existing)
        async with conn.transaction():
            await conn.execute(sql)

        counts = {
            "shoots": await conn.fetchval("SELECT COUNT(*) FROM shoots"),
            "clips": await conn.fetchval("SELECT COUNT(*) FROM clips"),
            "posts": await conn.fetchval("SELECT COUNT(*) FROM posts"),
        }
        log.info("Seed complete: %s", counts)
        return {"status": "inserted", "counts": counts}
    finally:
        await conn.close()


async def _run(event: dict) -> dict:
    payload = event or {}
    bucket = (
        payload.get("bucket")
        or os.environ.get(_DEFAULT_BUCKET_ENV)
        or ""
    )
    key = (
        payload.get("key")
        or os.environ.get(_DEFAULT_KEY_ENV)
        or ""
    )
    if not bucket or not key:
        return {
            "status": "error",
            "reason": (
                "bucket and key required - pass in payload or set "
                f"{_DEFAULT_BUCKET_ENV} / {_DEFAULT_KEY_ENV} env vars"
            ),
        }

    result = await _restore(bucket, key)
    return {"job": "clips_seed", **result}


def handler(event: dict, context) -> dict:
    install_paths()
    configure_logging()
    return run_async(_run(event or {}))
