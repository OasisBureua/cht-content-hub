"""HCP Intel orchestrator — polls due subscriptions and persists signals.

Runs every 30min via APScheduler. Per invocation:
1. Select subscriptions that are due (resolution_status in ('auto_resolved',
   'manually_resolved'), is_active=true, last_polled_at + cadence_hours ago
   or null), capped at MAX_PER_CYCLE.
2. Group by source, process each group.
3. For each subscription: fetch → upsert feed_items (dedup) → extract signals
   → insert hcp_signals + signal_drugs.
4. Update last_polled_at on success; increment consecutive_failures on error
   and deactivate after FAILURE_THRESHOLD.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import and_, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session_maker
from hcp_intel.models import (
    FeedItem,
    FeedSubscription,
    HCPSignal,
    SignalDrug,
)
from hcp_intel.sources import bluesky as bsky_src
from hcp_intel.sources import clinicaltrials as ct_src
from hcp_intel.sources import google_news as gn_src
from hcp_intel.sources import openalex as oa_src
from hcp_intel.sources import pubmed as pm_src
from hcp_intel.sources import youtube as yt_src
from hcp_intel.sources.common import FeedItemPayload, SignalPayload

log = logging.getLogger(__name__)

MAX_PER_CYCLE = 500
FAILURE_THRESHOLD = 5


@dataclass
class PollStats:
    processed: int = 0
    items_ingested: int = 0
    signals_written: int = 0
    errors: int = 0


# ─── due selection ──────────────────────────────────────────────────────────


async def select_due_subscriptions(
    db: AsyncSession, *, limit: int = MAX_PER_CYCLE, now: datetime | None = None
) -> list[FeedSubscription]:
    """Subscriptions whose cadence has elapsed and are ready to poll."""
    now = now or datetime.utcnow()
    # Compute "next poll time" as last_polled_at + cadence_hours * interval.
    # Postgres expression: last_polled_at + make_interval(hours => cadence_hours)
    stmt = (
        select(FeedSubscription)
        .where(
            FeedSubscription.is_active.is_(True),
            FeedSubscription.resolution_status.in_(
                ["auto_resolved", "manually_resolved"]
            ),
            or_(
                FeedSubscription.last_polled_at.is_(None),
                FeedSubscription.last_polled_at
                + (FeedSubscription.cadence_hours * text("interval '1 hour'"))
                <= now,
            ),
        )
        .order_by(
            FeedSubscription.last_polled_at.asc().nulls_first(),
        )
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ─── per-source fetch + extract ─────────────────────────────────────────────


async def _fetch_for_subscription(
    sub: FeedSubscription,
    client: httpx.AsyncClient,
    *,
    hcp_fn: str,
    hcp_ln: str,
    hcp_city: str | None = None,
    hcp_state: str | None = None,
    hcp_hospital: str | None = None,
) -> list[FeedItemPayload]:
    """Dispatch to the right source module."""
    if sub.source == "pubmed":
        since = sub.last_success_at
        # strict=True post-filters by full-name OR last+initial-with-affiliation
        # to stop cross-author bleed (e.g. Jianxing Shen showing on John Shen's
        # profile because both index as "Shen J").
        papers = await pm_src.fetch_papers_for_hcp(
            hcp_fn, hcp_ln, since=since, client=client,
            city=hcp_city, state=hcp_state, hospital=hcp_hospital,
            strict=True,
        )
        return [pm_src.paper_to_feed_item(p) for p in papers if p.pmid]
    if sub.source == "clinicaltrials":
        trials = await ct_src.fetch_trials_for_hcp(
            hcp_fn, hcp_ln, since=sub.last_success_at, client=client,
            city=hcp_city, state=hcp_state, hospital=hcp_hospital,
        )
        return [ct_src.trial_to_feed_item(t) for t in trials if t.nct_id]
    if sub.source == "youtube":
        if not sub.external_handle:
            return []
        return await yt_src.fetch_for_channel(sub.external_handle, client=client)
    if sub.source == "bluesky":
        if not sub.external_handle:
            return []
        return await bsky_src.fetch_for_handle(sub.external_handle, client=client)
    if sub.source == "google_news":
        if not sub.external_handle:
            return []
        return await gn_src.fetch_for_query(sub.external_handle, client=client)
    if sub.source == "openalex":
        # external_handle holds the locked OpenAlex author_id (e.g. "A1234567890").
        # Subscriptions without one are awaiting auto-resolution by the
        # openalex_backfill job; skip them so we don't re-resolve every poll.
        if not sub.external_handle:
            return []
        works = await oa_src.fetch_works(
            sub.external_handle, since=sub.last_success_at, client=client
        )
        return [oa_src.work_to_feed_item(w) for w in works if w.openalex_id]
    log.warning("unknown source %r on subscription %s", sub.source, sub.id)
    return []


def _extract_for_source(
    source: str,
    item: FeedItemPayload,
    *,
    hospital_affiliations: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> list[SignalPayload]:
    if source == "pubmed":
        return pm_src.extract_signals(item)
    if source == "clinicaltrials":
        return ct_src.extract_signals(item)
    if source == "youtube":
        return yt_src.extract_signals(item)
    if source == "bluesky":
        return bsky_src.extract_signals(item)
    if source == "google_news":
        return gn_src.extract_signals(
            item,
            hospital_affiliations=hospital_affiliations,
            first_name=first_name,
            last_name=last_name,
        )
    if source == "openalex":
        return oa_src.extract_signals(item)
    return []


# ─── persist ────────────────────────────────────────────────────────────────


async def _upsert_feed_item(
    db: AsyncSession, sub: FeedSubscription, payload: FeedItemPayload
) -> tuple[FeedItem, bool]:
    """Insert-or-ignore on (subscription_id, external_id). Returns (item, is_new)."""
    existing = (
        await db.execute(
            select(FeedItem).where(
                FeedItem.subscription_id == sub.id,
                FeedItem.external_id == payload.external_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False
    item = FeedItem(
        subscription_id=sub.id,
        external_id=payload.external_id,
        title=payload.title,
        url=payload.url,
        published_at=payload.published_at,
        raw_json=payload.raw,
    )
    db.add(item)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = (
            await db.execute(
                select(FeedItem).where(
                    FeedItem.subscription_id == sub.id,
                    FeedItem.external_id == payload.external_id,
                )
            )
        ).scalar_one()
        return existing, False
    return item, True


async def _write_signals(
    db: AsyncSession,
    sub: FeedSubscription,
    item: FeedItem,
    signals: list[SignalPayload],
) -> int:
    """Persist signals + drug join rows. Idempotent: skip if a matching
    (hcp_npi, derived_from_item_id, signal_type) already exists."""
    if not signals:
        return 0
    written = 0
    for s in signals:
        already = (
            await db.execute(
                select(HCPSignal).where(
                    HCPSignal.hcp_npi == sub.hcp_npi,
                    HCPSignal.derived_from_item_id == item.id,
                    HCPSignal.signal_type == s.signal_type,
                )
            )
        ).scalar_one_or_none()
        if already is not None:
            continue
        signal = HCPSignal(
            hcp_npi=sub.hcp_npi,
            signal_type=s.signal_type,
            observed_at=s.observed_at,
            source=sub.source,
            derived_from_item_id=item.id,
            title=s.title,
            url=s.url,
            summary=s.summary,
            entities_json=s.entities,
        )
        db.add(signal)
        await db.flush()
        for d in s.drugs:
            db.add(
                SignalDrug(
                    signal_id=signal.id,
                    hcp_npi=sub.hcp_npi,
                    observed_at=s.observed_at,
                    drug_normalized=d.drug_normalized,
                    drug_source_term=d.drug_source_term,
                    source_field=d.source_field,
                )
            )
        written += 1
    return written


# ─── main entry: poll one subscription ──────────────────────────────────────


async def poll_subscription(
    db: AsyncSession,
    sub: FeedSubscription,
    client: httpx.AsyncClient,
    *,
    hcp_fn: str,
    hcp_ln: str,
    hospital_affiliations: str | None = None,
    hcp_city: str | None = None,
    hcp_state: str | None = None,
) -> tuple[int, int]:
    """Returns (items_new, signals_written). Raises on fatal fetch errors."""
    payloads = await _fetch_for_subscription(
        sub, client, hcp_fn=hcp_fn, hcp_ln=hcp_ln,
        hcp_city=hcp_city, hcp_state=hcp_state,
        hcp_hospital=hospital_affiliations,
    )
    items_new = 0
    signals_written = 0
    for p in payloads:
        item, is_new = await _upsert_feed_item(db, sub, p)
        if is_new:
            items_new += 1
        signals = _extract_for_source(
            sub.source, p,
            hospital_affiliations=hospital_affiliations,
            first_name=hcp_fn, last_name=hcp_ln,
        )
        signals_written += await _write_signals(db, sub, item, signals)
    return items_new, signals_written


# ─── top-level job ──────────────────────────────────────────────────────────


async def poll_due_subscriptions() -> PollStats:
    """APScheduler entry point. Runs every ~30min."""
    stats = PollStats()
    async with async_session_maker() as db:
        due = await select_due_subscriptions(db)
        if not due:
            log.info("hcp_intel.poll: no due subscriptions")
            return stats

        # Materialize sub keys up front so we never depend on ORM attribute
        # state after rollbacks/commits.
        due_keys = [(s.id, s.hcp_npi, s.source) for s in due]
        npis = sorted({n for _, n, _ in due_keys})
        hcp_rows = (
            await db.execute(
                text(
                    "SELECT npi, first_name, last_name, hospital_affiliations, "
                    "city, state FROM hcps WHERE npi = ANY(:npis)"
                ),
                {"npis": npis},
            )
        ).all()
        names = {
            r.npi: (r.first_name, r.last_name, r.hospital_affiliations, r.city, r.state)
            for r in hcp_rows
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            for sub_id, sub_npi, sub_source in due_keys:
                sub = (
                    await db.execute(
                        select(FeedSubscription).where(
                            FeedSubscription.id == sub_id
                        )
                    )
                ).scalar_one()
                fn, ln, hosp, city, state = names.get(
                    sub_npi, ("", "", None, None, None)
                )
                if not ln:
                    log.warning(
                        "hcp_intel.poll: no hcp row for npi %s, skipping", sub_npi
                    )
                    continue
                started = datetime.utcnow()
                try:
                    items_new, signals = await poll_subscription(
                        db, sub, client, hcp_fn=fn, hcp_ln=ln,
                        hospital_affiliations=hosp,
                        hcp_city=city, hcp_state=state,
                    )
                    sub.last_polled_at = started
                    sub.last_success_at = started
                    sub.consecutive_failures = 0
                    sub.last_error = None
                    await db.commit()
                    stats.processed += 1
                    stats.items_ingested += items_new
                    stats.signals_written += signals
                except Exception as exc:  # noqa: BLE001
                    await db.rollback()
                    stats.errors += 1
                    sub_db = (
                        await db.execute(
                            select(FeedSubscription).where(
                                FeedSubscription.id == sub_id
                            )
                        )
                    ).scalar_one()
                    sub_db.last_polled_at = started
                    sub_db.consecutive_failures = (
                        (sub_db.consecutive_failures or 0) + 1
                    )
                    sub_db.last_error = str(exc)[:500]
                    if sub_db.consecutive_failures >= FAILURE_THRESHOLD:
                        sub_db.is_active = False
                        log.error(
                            "hcp_intel.poll: deactivating %s after %d failures: %s",
                            sub_id,
                            sub_db.consecutive_failures,
                            exc,
                        )
                    else:
                        log.warning(
                            "hcp_intel.poll: sub %s failed (%d/%d): %s",
                            sub_id,
                            sub_db.consecutive_failures,
                            FAILURE_THRESHOLD,
                            exc,
                        )
                    await db.commit()

    log.info(
        "hcp_intel.poll: processed=%d items=%d signals=%d errors=%d",
        stats.processed,
        stats.items_ingested,
        stats.signals_written,
        stats.errors,
    )
    return stats
