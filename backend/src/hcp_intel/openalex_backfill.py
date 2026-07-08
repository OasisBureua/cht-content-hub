"""One-off backfill: resolve HCPs to OpenAlex author_ids.

Iterates HCPs where `openalex_resolution_status = 'unresolved'`, calls the
OpenAlex resolver, and persists the outcome.

Run as:
  ./venv/bin/python -m hcp_intel.openalex_backfill [--limit N] [--batch 50]

Expected status distribution across 21k HCPs (rough estimate from prototype):
  auto_locked   ~50-60%   top score >= 5 AND gap >= 3
  needs_review  ~25-35%   top score ambiguous, candidates persisted for UI
  no_match      ~10-15%   no usable candidates

Resumable: skips HCPs already resolved.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import asdict
from datetime import datetime

import httpx
from sqlalchemy import select, update

from database import async_session_maker
from hcp_intel.models import HCP
from hcp_intel.sources import openalex as oa

log = logging.getLogger("openalex_backfill")


def _status_from_confidence(confidence: str) -> str:
    if confidence == "high":
        return "auto_locked"
    if confidence in ("medium", "ambiguous"):
        return "needs_review"
    return "no_match"


async def resolve_one(
    client: httpx.AsyncClient, hcp: HCP
) -> tuple[str, str | None, list[dict]]:
    """Returns (status, author_id, candidates_json)."""
    try:
        result = await oa.resolve_author(
            hcp.first_name, hcp.last_name,
            hcp.hospital_affiliations,
            client=client,
        )
    except Exception as e:
        log.warning("resolve failed for %s %s %s: %s",
                    hcp.npi, hcp.first_name, hcp.last_name, e)
        return ("unresolved", None, [])

    status = _status_from_confidence(result.confidence)
    candidates = [asdict(c) for c in result.candidates]
    return (status, result.author_id, candidates)


async def backfill(limit: int | None = None, batch_size: int = 50) -> dict:
    counts = {"auto_locked": 0, "needs_review": 0, "no_match": 0, "errored": 0}
    total = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            async with async_session_maker() as db:
                q = (
                    select(HCP)
                    .where(HCP.openalex_resolution_status == "unresolved")
                    .limit(batch_size)
                )
                rows = (await db.execute(q)).scalars().all()

            if not rows:
                break

            for hcp in rows:
                status, author_id, candidates = await resolve_one(client, hcp)
                if status == "unresolved":
                    counts["errored"] += 1
                    # Don't persist — leave as unresolved so we retry next run.
                    continue

                async with async_session_maker() as db:
                    await db.execute(
                        update(HCP)
                        .where(HCP.npi == hcp.npi)
                        .values(
                            openalex_author_id=author_id,
                            openalex_resolution_status=status,
                            openalex_candidates=candidates,
                            openalex_resolved_at=datetime.utcnow(),
                        )
                    )
                    # Write-through to feed_subscriptions so the orchestrator can
                    # actually poll OpenAlex for this HCP. Without this, the HCP
                    # row has an author_id but the subscription's external_handle
                    # stays NULL and polling silently no-ops.
                    if status in ("auto_locked", "manually_locked"):
                        from hcp_intel.openalex_subscription_sync import sync_one
                        await sync_one(db, hcp.npi)
                    await db.commit()

                counts[status] = counts.get(status, 0) + 1
                total += 1
                if limit and total >= limit:
                    log.info("reached limit=%d, stopping", limit)
                    return counts

            log.info(
                "progress: total=%d auto=%d review=%d nomatch=%d err=%d",
                total, counts["auto_locked"], counts["needs_review"],
                counts["no_match"], counts["errored"],
            )

    return counts


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="Max HCPs to resolve in this run (default: all)")
    parser.add_argument("--batch", type=int, default=50,
                        help="DB batch size (default: 50)")
    args = parser.parse_args()

    counts = asyncio.run(backfill(limit=args.limit, batch_size=args.batch))
    print("Final counts:", counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
