"""SCRUM-65 admin KOL intel endpoints — deep-dive data for CHT admin dashboard.

Covers 5 endpoints under /api/admin/kols/{slug}/*:
- /engagement    — WebinarAttendance aggregates
- /publications  — HCPSignal WHERE signal_type='publication'
- /open-payments — OpenPaymentsRecord rows + summary
- /trials        — HCPSignal WHERE signal_type='trial'
- /news          — HCPSignal WHERE signal_type='news_article'
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from conftest import API_KEY, api_headers
from hcp_intel.models import HCP, HCPSignal
from models.kol import KOL
from utils.kol_public import kol_slug


def _dt(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def kol_with_npi(db_session: AsyncSession) -> KOL:
    hcp = HCP(npi="1234567890", first_name="Jane", last_name="Roe")
    kol = KOL(
        slug=kol_slug("Dr. Jane Roe"),
        name="Dr. Jane Roe",
        specialty="Medical Oncology",
        institution="UCSF",
        region="california",
        hcp_npi="1234567890",
    )
    db_session.add_all([hcp, kol])
    await db_session.flush()
    return kol


@pytest.fixture
async def kol_no_npi(db_session: AsyncSession) -> KOL:
    kol = KOL(
        slug=kol_slug("Dr. Nomatch"),
        name="Dr. Nomatch",
        specialty="Cardiology",
        region="california",
    )
    db_session.add(kol)
    await db_session.flush()
    return kol


async def _insert_signal(
    db: AsyncSession,
    npi: str,
    signal_type: str,
    *,
    title: str,
    url: str | None = None,
    summary: str | None = None,
    observed_at: datetime | None = None,
    source: str = "openalex",
    entities: dict | None = None,
) -> str:
    """Bypass ORM — SQLite JSON column doesn't round-trip dicts via the ORM
    the way JSONB does on Postgres. Insert via raw text() to keep the fixture
    tight."""
    import json as _json

    sid = str(uuid4())
    await db.execute(
        text(
            "INSERT INTO hcp_signals (id, hcp_npi, signal_type, observed_at, source, title, url, summary, entities_json) "
            "VALUES (:id, :npi, :st, :obs, :src, :title, :url, :summary, :ej)"
        ),
        {
            "id": sid,
            "npi": npi,
            "st": signal_type,
            "obs": observed_at or _dt(2026, 1, 1),
            "src": source,
            "title": title,
            "url": url,
            "summary": summary,
            "ej": _json.dumps(entities) if entities else None,
        },
    )
    return sid


async def _insert_webinar_attendance(
    db: AsyncSession,
    npi: str,
    *,
    attended: bool,
    rsvped: bool = True,
    asked_question: bool = False,
    survey_submitted: bool = False,
    created_at: datetime | None = None,
) -> None:
    event_id = str(uuid4())
    await db.execute(
        text(
            "INSERT INTO webinar_events (id, title, scheduled_start, created_at) "
            "VALUES (:id, :t, :s, :c)"
        ),
        {"id": event_id, "t": "Test Webinar", "s": _dt(2026, 1, 1), "c": _dt(2026, 1, 1)},
    )
    await db.execute(
        text(
            "INSERT INTO webinar_attendance (id, event_id, hcp_npi, rsvped, attended, "
            "asked_question, survey_submitted, created_at) "
            "VALUES (:id, :eid, :npi, :rsvp, :att, :ask, :sur, :c)"
        ),
        {
            "id": str(uuid4()),
            "eid": event_id,
            "npi": npi,
            "rsvp": rsvped,
            "att": attended,
            "ask": asked_question,
            "sur": survey_submitted,
            "c": created_at or _dt(2026, 6, 1),
        },
    )


async def _insert_open_payment(
    db: AsyncSession,
    npi: str,
    *,
    program_year: int,
    payment_type: str,
    amount_usd: float,
    company_name: str | None = None,
    drug_name: str | None = None,
) -> None:
    await db.execute(
        text(
            "INSERT INTO open_payments_records "
            "(record_id, hcp_npi, program_year, payment_type, amount_usd, company_name, drug_name, payment_date) "
            "VALUES (:rid, :npi, :yr, :pt, :amt, :co, :drug, :pd)"
        ),
        {
            "rid": str(uuid4()),
            "npi": npi,
            "yr": program_year,
            "pt": payment_type,
            "amt": amount_usd,
            "co": company_name,
            "drug": drug_name,
            "pd": _dt(program_year, 6, 15),
        },
    )


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_endpoints_require_api_key(client: AsyncClient, kol_with_npi):
    slug = kol_with_npi.slug
    for path in ("engagement", "publications", "open-payments", "trials", "news"):
        r = await client.get(f"/api/admin/kols/{slug}/{path}")
        assert r.status_code == 401, path


# ---------------------------------------------------------------------------
# KOL-not-found + no-NPI cases (common shape for all 5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_endpoints_404_when_slug_unknown(client: AsyncClient):
    for path in ("engagement", "publications", "open-payments", "trials", "news"):
        r = await client.get(
            f"/api/admin/kols/does-not-exist/{path}", headers=api_headers()
        )
        assert r.status_code == 404, path


@pytest.mark.asyncio
async def test_all_endpoints_404_when_kol_has_no_npi(client: AsyncClient, kol_no_npi):
    slug = kol_no_npi.slug
    for path in ("engagement", "publications", "open-payments", "trials", "news"):
        r = await client.get(f"/api/admin/kols/{slug}/{path}", headers=api_headers())
        assert r.status_code == 404, path
        # /api/admin/* errors use NestJS-style envelope: {statusCode, message, error}
        body = r.json()
        assert "hcp npi" in body["message"].lower()


# ---------------------------------------------------------------------------
# /engagement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_engagement_empty_state(client: AsyncClient, kol_with_npi):
    r = await client.get(
        f"/api/admin/kols/{kol_with_npi.slug}/engagement", headers=api_headers()
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "webinars_attended": 0,
        "webinars_rsvp_only": 0,
        "questions_asked": 0,
        "surveys_submitted": 0,
        "first_attendance_at": None,
        "last_attendance_at": None,
        "qa_rate": None,
        "survey_rate": None,
        "days_since_last_engagement": None,
    }


@pytest.mark.asyncio
async def test_engagement_computes_aggregates(
    client: AsyncClient, kol_with_npi, db_session: AsyncSession
):
    npi = kol_with_npi.hcp_npi
    # 3 attended, 1 rsvp-only, 2 asked questions, 1 survey
    await _insert_webinar_attendance(db_session, npi, attended=True, asked_question=True, survey_submitted=True, created_at=_dt(2026, 6, 1))
    await _insert_webinar_attendance(db_session, npi, attended=True, asked_question=True, created_at=_dt(2026, 7, 1))
    await _insert_webinar_attendance(db_session, npi, attended=True, created_at=_dt(2026, 5, 1))
    await _insert_webinar_attendance(db_session, npi, attended=False, rsvped=True, created_at=_dt(2026, 4, 1))
    await db_session.flush()

    r = await client.get(
        f"/api/admin/kols/{kol_with_npi.slug}/engagement", headers=api_headers()
    )
    assert r.status_code == 200
    body = r.json()
    assert body["webinars_attended"] == 3
    assert body["webinars_rsvp_only"] == 1
    assert body["questions_asked"] == 2
    assert body["surveys_submitted"] == 1
    assert body["qa_rate"] == pytest.approx(2 / 3)
    assert body["survey_rate"] == pytest.approx(1 / 3)
    # first/last attendance are from attended-only rows: 2026-05-01 and 2026-07-01
    assert body["first_attendance_at"].startswith("2026-05")
    assert body["last_attendance_at"].startswith("2026-07")


# ---------------------------------------------------------------------------
# /publications
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publications_empty_state(client: AsyncClient, kol_with_npi):
    r = await client.get(
        f"/api/admin/kols/{kol_with_npi.slug}/publications", headers=api_headers()
    )
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0}


@pytest.mark.asyncio
async def test_publications_returns_signals(
    client: AsyncClient, kol_with_npi, db_session: AsyncSession
):
    npi = kol_with_npi.hcp_npi
    await _insert_signal(
        db_session, npi, "publication",
        title="Paper A", url="https://example.com/a",
        observed_at=_dt(2026, 6, 1),
        entities={"journal": "JCO", "is_first_author": True},
    )
    await _insert_signal(
        db_session, npi, "publication",
        title="Paper B", observed_at=_dt(2025, 6, 1),
        entities={"journal": "NEJM", "is_last_author": True},
    )
    # A trial signal — must NOT appear in publications
    await _insert_signal(db_session, npi, "trial", title="Trial X")
    await db_session.flush()

    r = await client.get(
        f"/api/admin/kols/{kol_with_npi.slug}/publications", headers=api_headers()
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    titles = [it["title"] for it in body["items"]]
    assert titles == ["Paper A", "Paper B"]  # ordered by observed_at desc
    assert body["items"][0]["is_first_author"] is True
    assert body["items"][0]["journal"] == "JCO"
    assert body["items"][1]["is_last_author"] is True


# ---------------------------------------------------------------------------
# /open-payments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_open_payments_empty_state(client: AsyncClient, kol_with_npi):
    r = await client.get(
        f"/api/admin/kols/{kol_with_npi.slug}/open-payments", headers=api_headers()
    )
    assert r.status_code == 200
    body = r.json()
    assert body["records"] == []
    assert body["summary"]["total_records"] == 0
    assert Decimal(body["summary"]["total_amount_usd"]) == Decimal("0")


@pytest.mark.asyncio
async def test_open_payments_summary_and_records(
    client: AsyncClient, kol_with_npi, db_session: AsyncSession
):
    npi = kol_with_npi.hcp_npi
    await _insert_open_payment(db_session, npi, program_year=2024, payment_type="general", amount_usd=1500.0, company_name="AstraZeneca")
    await _insert_open_payment(db_session, npi, program_year=2024, payment_type="general", amount_usd=500.0, company_name="AstraZeneca")
    await _insert_open_payment(db_session, npi, program_year=2023, payment_type="research", amount_usd=200.0, company_name="DaiichiSankyo")
    await db_session.flush()

    r = await client.get(
        f"/api/admin/kols/{kol_with_npi.slug}/open-payments", headers=api_headers()
    )
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["total_records"] == 3
    assert Decimal(body["summary"]["total_amount_usd"]) == Decimal("2200.0")
    assert body["summary"]["year_range"] == [2023, 2024]
    assert body["summary"]["top_company"] == "AstraZeneca"
    assert Decimal(body["summary"]["top_company_amount_usd"]) == Decimal("2000.0")
    assert len(body["records"]) == 3


# ---------------------------------------------------------------------------
# /trials
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trials_empty_state(client: AsyncClient, kol_with_npi):
    r = await client.get(
        f"/api/admin/kols/{kol_with_npi.slug}/trials", headers=api_headers()
    )
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0}


@pytest.mark.asyncio
async def test_trials_returns_signals_with_entities(
    client: AsyncClient, kol_with_npi, db_session: AsyncSession
):
    npi = kol_with_npi.hcp_npi
    await _insert_signal(
        db_session, npi, "trial",
        title="TROPION-Breast09",
        source="clinicaltrials",
        entities={"nct_id": "NCT06111111", "phase": "Phase III"},
        observed_at=_dt(2026, 3, 15),
    )
    # A publication — must NOT appear
    await _insert_signal(db_session, npi, "publication", title="Paper")
    await db_session.flush()

    r = await client.get(
        f"/api/admin/kols/{kol_with_npi.slug}/trials", headers=api_headers()
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "TROPION-Breast09"
    assert body["items"][0]["source"] == "clinicaltrials"
    assert body["items"][0]["entities"]["nct_id"] == "NCT06111111"


# ---------------------------------------------------------------------------
# /news
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_news_empty_state(client: AsyncClient, kol_with_npi):
    r = await client.get(
        f"/api/admin/kols/{kol_with_npi.slug}/news", headers=api_headers()
    )
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0}


@pytest.mark.asyncio
async def test_news_returns_signals_with_source_name(
    client: AsyncClient, kol_with_npi, db_session: AsyncSession
):
    npi = kol_with_npi.hcp_npi
    await _insert_signal(
        db_session, npi, "news_article",
        title="Dr. Roe on TDXd trial",
        url="https://example.com/news1",
        source="google_news",
        entities={"source_name": "STAT News"},
        observed_at=_dt(2026, 7, 10),
    )
    # A trial — must NOT appear in news
    await _insert_signal(db_session, npi, "trial", title="Trial X")
    await db_session.flush()

    r = await client.get(
        f"/api/admin/kols/{kol_with_npi.slug}/news", headers=api_headers()
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["source_name"] == "STAT News"
    assert body["items"][0]["source"] == "google_news"
