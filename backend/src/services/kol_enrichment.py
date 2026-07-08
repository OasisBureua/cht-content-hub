"""HCP-derived enrichment for public KOL responses (CHT /kol-network compat)."""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import async_session_maker
from hcp_intel.models import HCP, HCPAIBrief, HCPSignal, OpenPaymentsRecord
from schemas.public import PublicKOLAIBrief, PublicKOLIntel

# Section-heading → schema-field mapping for HCP AI briefs.
# MediaHub's brief generator emits Markdown with these three fixed H2 headings;
# the CHT KOL profile Background tab renders each as a labeled section.
_BRIEF_HEADING_TO_FIELD: dict[str, str] = {
    "who they are": "whoTheyAre",
    "what they focus on": "focus",
    "chm context": "chmContext",
}


def _location(hcp: HCP) -> str | None:
    parts = [p for p in (hcp.city, hcp.state) if p]
    return ", ".join(parts) if parts else None


def _parse_brief_sections(markdown: str) -> PublicKOLAIBrief:
    """Split a `## Who they are / ## What they focus on / ## CHM context` brief.

    MediaHub stores each HCP AI brief as a single markdown string. The CHT
    frontend expects three separate fields, one per section. This parser walks
    the markdown, groups lines under each recognized H2 heading, and returns
    them as fields on a `PublicKOLAIBrief`.

    Behavior:

    - Lines before the first recognized heading are ignored.
    - Unknown headings terminate the previous section and buffer nothing until
      the next recognized heading is seen.
    - Empty sections stay `None` (frontend renders nothing for them).
    - Whitespace-only sections normalize to `None`.
    """
    sections: dict[str, str | None] = {
        "whoTheyAre": None,
        "focus": None,
        "chmContext": None,
    }
    current_field: str | None = None
    buffer: list[str] = []

    def _flush() -> None:
        nonlocal buffer
        if current_field is None:
            buffer = []
            return
        body = "\n".join(buffer).strip()
        sections[current_field] = body or None
        buffer = []

    for line in markdown.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## "):
            _flush()
            heading = stripped.lstrip("#").strip().lower()
            current_field = _BRIEF_HEADING_TO_FIELD.get(heading)
        elif current_field is not None:
            buffer.append(line)
    _flush()

    return PublicKOLAIBrief(**sections)


async def _fetch_hcps(db: AsyncSession, npis: list[str]) -> dict[str, HCP]:
    rows = (await db.execute(select(HCP).where(HCP.npi.in_(npis)))).scalars().all()
    return {row.npi: row for row in rows}


async def _fetch_briefs(db: AsyncSession, npis: list[str]) -> dict[str, HCPAIBrief]:
    rows = (
        await db.execute(select(HCPAIBrief).where(HCPAIBrief.hcp_npi.in_(npis)))
    ).scalars().all()
    return {row.hcp_npi: row for row in rows}


async def _fetch_pub_counts(db: AsyncSession, npis: list[str]) -> dict[str, int]:
    rows = (
        await db.execute(
            select(HCPSignal.hcp_npi, func.count().label("cnt"))
            .where(
                HCPSignal.hcp_npi.in_(npis),
                HCPSignal.signal_type == "publication",
            )
            .group_by(HCPSignal.hcp_npi)
        )
    ).all()
    return {row.hcp_npi: int(row.cnt) for row in rows}


async def _fetch_payments(db: AsyncSession, npis: list[str]) -> dict[str, dict]:
    rows = (
        await db.execute(
            select(
                OpenPaymentsRecord.hcp_npi,
                func.coalesce(func.sum(OpenPaymentsRecord.amount_usd), 0).label(
                    "total"
                ),
                func.count().label("records"),
                func.min(OpenPaymentsRecord.program_year).label("year_min"),
                func.max(OpenPaymentsRecord.program_year).label("year_max"),
            )
            .where(OpenPaymentsRecord.hcp_npi.in_(npis))
            .group_by(OpenPaymentsRecord.hcp_npi)
        )
    ).all()
    return {
        row.hcp_npi: {
            "total": float(row.total or 0),
            "records": int(row.records or 0),
            "years": (
                f"{row.year_min}–{row.year_max}"
                if row.year_min and row.year_max and row.year_min != row.year_max
                else str(row.year_min or row.year_max or "")
            ),
        }
        for row in rows
    }


def _build_intel_map(
    npis: list[str],
    hcps: dict[str, HCP],
    briefs: dict[str, HCPAIBrief],
    pub_counts: dict[str, int],
    payments: dict[str, dict],
) -> dict[str, PublicKOLIntel]:
    out: dict[str, PublicKOLIntel] = {}
    for npi in npis:
        hcp = hcps.get(npi)
        if hcp is None:
            continue
        brief = briefs.get(npi)
        ai_brief: PublicKOLAIBrief | None = None
        if brief and brief.brief_markdown.strip():
            ai_brief = _parse_brief_sections(brief.brief_markdown.strip()[:4000])
        op = payments.get(npi)
        out[npi] = PublicKOLIntel(
            npi=npi,
            specialty=hcp.taxonomy,
            location=_location(hcp),
            email=hcp.email,
            affiliation=hcp.hospital_affiliations,
            publications_approx=pub_counts.get(npi),
            open_payments=op,
            ai_brief=ai_brief,
        )
    return out


async def load_intel_for_npis(
    db: AsyncSession, npis: list[str]
) -> dict[str, PublicKOLIntel]:
    if not npis:
        return {}

    # SQLite tests use a single connection/transaction; parallel sessions cannot see it.
    if get_settings().database_url.startswith("sqlite"):
        hcps = await _fetch_hcps(db, npis)
        briefs = await _fetch_briefs(db, npis)
        pub_counts = await _fetch_pub_counts(db, npis)
        payments = await _fetch_payments(db, npis)
        return _build_intel_map(npis, hcps, briefs, pub_counts, payments)

    async def _isolated(fetch):
        async with async_session_maker() as session:
            return await fetch(session, npis)

    hcps, briefs, pub_counts, payments = await asyncio.gather(
        _isolated(_fetch_hcps),
        _isolated(_fetch_briefs),
        _isolated(_fetch_pub_counts),
        _isolated(_fetch_payments),
    )
    return _build_intel_map(npis, hcps, briefs, pub_counts, payments)
