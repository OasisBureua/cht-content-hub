"""Admin KOL intel deep-dive API (SCRUM-65).

Five admin-only endpoints for the CHT admin KOL dashboard. Consumed via
CHT's `/api/admin/kol-network/:slug/*` proxy (SCRUM-65 CHT side).

Not exposed publicly. `/engagement` and `/open-payments` in particular are
individually-attributable data that should never leak to non-admin surfaces.

Auth: X-API-Key server-to-server (`verify_admin_api_key`). CHT enforces the
admin JWT + chm-* group check before proxying user requests here.

Routes (all under /api/admin/kols/{slug}):
- GET /engagement    — WebinarAttendance aggregates
- GET /publications  — HCPSignal WHERE signal_type='publication'
- GET /open-payments — OpenPaymentsRecord rows + rollup summary
- GET /trials        — HCPSignal WHERE signal_type='trial'
- GET /news          — HCPSignal WHERE signal_type='news_article'

`/brief` is intentionally omitted — the parsed 3-section brief is already
exposed on the public `/api/public/kols/{slug}` `intel.ai_brief` overlay
and re-shipping the raw markdown doesn't add value for the current admin UI.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from admin.deps import verify_admin_api_key
from database import get_db
from hcp_intel.models import HCPSignal, OpenPaymentsRecord, WebinarAttendance
from models.kol import KOL
from schemas.admin_kol_intel import (
    AdminKOLPublication,
    AdminKOLPublicationList,
    EngagementSignalsOut,
    NewsArticleOut,
    NewsOut,
    OpenPaymentsOut,
    OpenPaymentsRecordOut,
    OpenPaymentsSummary,
    TrialSignalOut,
    TrialsOut,
)
from services import kol_queries


router = APIRouter(prefix="/api/admin", tags=["admin-kol-intel"])


_NO_HCP_INTEL_DETAIL = "KOL has no matched HCP NPI — intel data unavailable."


def _require_npi(kol: KOL) -> str:
    if not kol.hcp_npi:
        raise HTTPException(status_code=404, detail=_NO_HCP_INTEL_DETAIL)
    return kol.hcp_npi


# ---------------------------------------------------------------------------
# /engagement
# ---------------------------------------------------------------------------


@router.get(
    "/kols/{slug}/engagement",
    response_model=EngagementSignalsOut,
    responses={404: {"description": "KOL not found, or KOL has no matched HCP NPI."}},
)
async def get_admin_kol_engagement(
    slug: str,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EngagementSignalsOut:
    """Aggregate webinar-engagement signals. Admin-only — individually attributable."""
    kol, _ = await kol_queries.get_kol_by_slug(db, slug)
    npi = _require_npi(kol)

    rows = list(
        (
            await db.execute(
                select(WebinarAttendance).where(WebinarAttendance.hcp_npi == npi)
            )
        ).scalars()
    )
    if not rows:
        return EngagementSignalsOut(
            webinars_attended=0,
            webinars_rsvp_only=0,
            questions_asked=0,
            surveys_submitted=0,
        )

    attended_rows = [r for r in rows if r.attended]
    attended = len(attended_rows)
    rsvp_only = sum(1 for r in rows if r.rsvped and not r.attended)
    asked = sum(1 for r in rows if r.asked_question)
    surveys = sum(1 for r in rows if r.survey_submitted)

    dt_source = attended_rows if attended_rows else rows
    dates = [r.created_at for r in dt_source if r.created_at is not None]
    first_at = min(dates) if dates else None
    last_at = max(dates) if dates else None

    days_since: int | None = None
    if last_at is not None:
        # WebinarAttendance.created_at is timezone-naive in the model; treat
        # as UTC. Avoid `utcnow()` deprecation warning.
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        if last_at.tzinfo is not None:
            last_at_cmp = last_at.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            last_at_cmp = last_at
        days_since = max((now_naive - last_at_cmp).days, 0)

    return EngagementSignalsOut(
        webinars_attended=attended,
        webinars_rsvp_only=rsvp_only,
        questions_asked=asked,
        surveys_submitted=surveys,
        first_attendance_at=first_at,
        last_attendance_at=last_at,
        qa_rate=(asked / attended) if attended else None,
        survey_rate=(surveys / attended) if attended else None,
        days_since_last_engagement=days_since,
    )


# ---------------------------------------------------------------------------
# /publications
# ---------------------------------------------------------------------------


@router.get(
    "/kols/{slug}/publications",
    response_model=AdminKOLPublicationList,
    responses={404: {"description": "KOL not found, or KOL has no matched HCP NPI."}},
)
async def get_admin_kol_publications(
    slug: str,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AdminKOLPublicationList:
    """Publication list backed by HCPSignal WHERE signal_type='publication'."""
    kol, _ = await kol_queries.get_kol_by_slug(db, slug)
    npi = _require_npi(kol)

    base_filter = (
        HCPSignal.hcp_npi == npi,
        HCPSignal.signal_type == "publication",
    )
    total = (
        await db.execute(select(func.count(HCPSignal.id)).where(*base_filter))
    ).scalar_one()

    rows = list(
        (
            await db.execute(
                select(HCPSignal)
                .where(*base_filter)
                .order_by(HCPSignal.observed_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
    )

    items = [
        AdminKOLPublication(
            id=s.id,
            title=s.title or "(untitled publication)",
            url=s.url,
            journal=(s.entities_json or {}).get("journal"),
            published_at=s.observed_at,
            is_first_author=bool((s.entities_json or {}).get("is_first_author")),
            is_last_author=bool((s.entities_json or {}).get("is_last_author")),
        )
        for s in rows
    ]
    return AdminKOLPublicationList(items=items, total=total)


# ---------------------------------------------------------------------------
# /open-payments
# ---------------------------------------------------------------------------


@router.get(
    "/kols/{slug}/open-payments",
    response_model=OpenPaymentsOut,
    responses={404: {"description": "KOL not found, or KOL has no matched HCP NPI."}},
)
async def get_admin_kol_open_payments(
    slug: str,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=200, ge=1, le=1000),
) -> OpenPaymentsOut:
    """CMS Open Payments disclosures. Admin-only surface."""
    kol, _ = await kol_queries.get_kol_by_slug(db, slug)
    npi = _require_npi(kol)

    rows = list(
        (
            await db.execute(
                select(OpenPaymentsRecord)
                .where(OpenPaymentsRecord.hcp_npi == npi)
                .order_by(
                    OpenPaymentsRecord.program_year.desc(),
                    OpenPaymentsRecord.payment_date.desc(),
                )
                .limit(limit)
            )
        ).scalars()
    )

    total_amount = sum(
        (r.amount_usd for r in rows if r.amount_usd is not None), Decimal("0")
    )
    years = [r.program_year for r in rows]
    year_range = (min(years), max(years)) if years else None

    company_totals: Counter[str] = Counter()
    for r in rows:
        if r.company_name and r.amount_usd is not None:
            company_totals[r.company_name] += float(r.amount_usd)
    top_company = None
    top_company_amount: Decimal | None = None
    if company_totals:
        name, amount = company_totals.most_common(1)[0]
        top_company = name
        top_company_amount = Decimal(str(amount))

    summary = OpenPaymentsSummary(
        total_records=len(rows),
        total_amount_usd=total_amount,
        year_range=year_range,
        top_company=top_company,
        top_company_amount_usd=top_company_amount,
    )

    return OpenPaymentsOut(
        summary=summary,
        records=[
            OpenPaymentsRecordOut(
                record_id=r.record_id,
                program_year=r.program_year,
                payment_type=r.payment_type,
                payment_date=r.payment_date,
                amount_usd=r.amount_usd,
                nature_of_payment=r.nature_of_payment,
                company_name=r.company_name,
                drug_name=r.drug_name,
                drug_normalized=r.drug_normalized,
            )
            for r in rows
        ],
    )


# ---------------------------------------------------------------------------
# /trials
# ---------------------------------------------------------------------------


@router.get(
    "/kols/{slug}/trials",
    response_model=TrialsOut,
    responses={404: {"description": "KOL not found, or KOL has no matched HCP NPI."}},
)
async def get_admin_kol_trials(
    slug: str,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> TrialsOut:
    """ClinicalTrials.gov signals for this KOL (HCPSignal.signal_type='trial')."""
    kol, _ = await kol_queries.get_kol_by_slug(db, slug)
    npi = _require_npi(kol)
    return await _list_signals(db, npi, signal_type="trial", limit=limit, offset=offset, out_cls=TrialsOut)


# ---------------------------------------------------------------------------
# /news
# ---------------------------------------------------------------------------


@router.get(
    "/kols/{slug}/news",
    response_model=NewsOut,
    responses={404: {"description": "KOL not found, or KOL has no matched HCP NPI."}},
)
async def get_admin_kol_news(
    slug: str,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> NewsOut:
    """News mentions for this KOL (HCPSignal.signal_type='news_article')."""
    kol, _ = await kol_queries.get_kol_by_slug(db, slug)
    npi = _require_npi(kol)
    return await _list_signals(db, npi, signal_type="news_article", limit=limit, offset=offset, out_cls=NewsOut)


# ---------------------------------------------------------------------------
# Shared HCPSignal query helper (trials + news use it)
# ---------------------------------------------------------------------------


async def _list_signals(
    db: AsyncSession,
    npi: str,
    *,
    signal_type: str,
    limit: int,
    offset: int,
    out_cls: type,
):
    base_filter = (
        HCPSignal.hcp_npi == npi,
        HCPSignal.signal_type == signal_type,
    )
    total = (
        await db.execute(select(func.count(HCPSignal.id)).where(*base_filter))
    ).scalar_one()
    rows = list(
        (
            await db.execute(
                select(HCPSignal)
                .where(*base_filter)
                .order_by(HCPSignal.observed_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
    )

    if out_cls is TrialsOut:
        items = [
            TrialSignalOut(
                id=s.id,
                observed_at=s.observed_at,
                title=s.title,
                url=s.url,
                summary=s.summary,
                source=s.source,
                entities=s.entities_json,
            )
            for s in rows
        ]
        return TrialsOut(items=items, total=total)

    # NewsOut path
    items = [
        NewsArticleOut(
            id=s.id,
            observed_at=s.observed_at,
            title=s.title,
            url=s.url,
            summary=s.summary,
            source=s.source,
            source_name=(s.entities_json or {}).get("source_name"),
        )
        for s in rows
    ]
    return NewsOut(items=items, total=total)
