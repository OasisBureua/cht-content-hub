"""Admin KOL intel schemas (SCRUM-65).

Response shapes for `/api/admin/kols/{slug}/{engagement,publications,open-payments,trials,news}`.
CHT admin dashboard consumes these via its `/api/admin/kol-network/:slug/*` proxy.

Shapes mirror MediaHub's legacy `routers/hcp_intel.py` inline schemas so CHT can
drop-in-replace its `intelApi.ts` fetch bodies with zero type churn (SCRUM-68).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# /engagement
# ---------------------------------------------------------------------------


class EngagementSignalsOut(BaseModel):
    """Aggregate webinar-attendance signals for one KOL.

    Backed by `WebinarAttendance` rows keyed on `hcp_npi`. All counts are
    lifetime; no time-windowing (yet). Rates are `count/attended` and null
    when the doctor has never attended a webinar.
    """

    webinars_attended: int
    webinars_rsvp_only: int
    questions_asked: int
    surveys_submitted: int
    first_attendance_at: datetime | None = None
    last_attendance_at: datetime | None = None
    qa_rate: float | None = None
    survey_rate: float | None = None
    days_since_last_engagement: int | None = None


# ---------------------------------------------------------------------------
# /publications
# ---------------------------------------------------------------------------


class AdminKOLPublication(BaseModel):
    """Single publication row for admin view.

    Mirrors public `PublicKOLPublication` for shape parity, with `id` added
    so admin dashboard can key React lists deterministically.
    """

    id: str
    title: str
    url: str | None = None
    journal: str | None = None
    published_at: datetime
    is_first_author: bool = False
    is_last_author: bool = False


class AdminKOLPublicationList(BaseModel):
    items: list[AdminKOLPublication]
    total: int


# ---------------------------------------------------------------------------
# /open-payments
# ---------------------------------------------------------------------------


class OpenPaymentsSummary(BaseModel):
    """Rollup across all `OpenPaymentsRecord` rows for a KOL."""

    total_records: int
    total_amount_usd: Decimal
    year_range: tuple[int, int] | None = None  # (earliest_year, latest_year)
    top_company: str | None = None
    top_company_amount_usd: Decimal | None = None


class OpenPaymentsRecordOut(BaseModel):
    """One CMS Open Payments disclosure row.

    `payment_type` is one of: general | research | ownership.
    """

    record_id: str
    program_year: int
    payment_type: str
    payment_date: datetime | None = None
    amount_usd: Decimal | None = None
    nature_of_payment: str | None = None
    company_name: str | None = None
    drug_name: str | None = None
    drug_normalized: str | None = None


class OpenPaymentsOut(BaseModel):
    """Admin-only surface — never expose over public API."""

    summary: OpenPaymentsSummary
    records: list[OpenPaymentsRecordOut]


# ---------------------------------------------------------------------------
# /trials
# ---------------------------------------------------------------------------


class TrialSignalOut(BaseModel):
    """A ClinicalTrials.gov signal derived from openalex/clinicaltrials ingest.

    Backed by `HCPSignal WHERE signal_type='trial'`. `entities_json` may carry
    NCT id, phase, and status when the source parsed them; we surface the
    stable fields (title, url, summary) plus that raw payload for admin
    display.
    """

    id: str
    observed_at: datetime
    title: str | None = None
    url: str | None = None
    summary: str | None = None
    source: str
    entities: dict | None = Field(default=None, description="Raw entities_json (NCT id, phase, status, etc.)")


class TrialsOut(BaseModel):
    items: list[TrialSignalOut]
    total: int


# ---------------------------------------------------------------------------
# /news
# ---------------------------------------------------------------------------


class NewsArticleOut(BaseModel):
    """A news mention derived from Google News (or other configured source).

    Backed by `HCPSignal WHERE signal_type='news_article'`. `source` is the
    upstream feed identifier (e.g., 'google_news'); `source_name` is a
    human-readable publication name pulled from `entities_json` when present.
    """

    id: str
    observed_at: datetime
    title: str | None = None
    url: str | None = None
    summary: str | None = None
    source: str
    source_name: str | None = None


class NewsOut(BaseModel):
    items: list[NewsArticleOut]
    total: int
