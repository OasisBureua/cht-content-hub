"""HCP-derived enrichment for public KOL responses (CHT /kol-network compat)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hcp_intel.models import HCP, HCPAIBrief, HCPSignal, OpenPaymentsRecord
from schemas.public import PublicKOLIntel


def _location(hcp: HCP) -> str | None:
    parts = [p for p in (hcp.city, hcp.state) if p]
    return ", ".join(parts) if parts else None


async def load_intel_for_npis(
    db: AsyncSession, npis: list[str]
) -> dict[str, PublicKOLIntel]:
    if not npis:
        return {}

    hcps = {
        row.npi: row
        for row in (await db.execute(select(HCP).where(HCP.npi.in_(npis)))).scalars()
    }

    briefs = {
        row.hcp_npi: row
        for row in (
            await db.execute(select(HCPAIBrief).where(HCPAIBrief.hcp_npi.in_(npis)))
        ).scalars()
    }

    pub_counts = {
        row.hcp_npi: int(row.cnt)
        for row in (
            await db.execute(
                select(HCPSignal.hcp_npi, func.count().label("cnt"))
                .where(
                    HCPSignal.hcp_npi.in_(npis),
                    HCPSignal.signal_type == "publication",
                )
                .group_by(HCPSignal.hcp_npi)
            )
        )
    }

    payment_rows = (
        await db.execute(
            select(
                OpenPaymentsRecord.hcp_npi,
                func.coalesce(func.sum(OpenPaymentsRecord.amount_usd), 0).label("total"),
                func.count().label("records"),
                func.min(OpenPaymentsRecord.program_year).label("year_min"),
                func.max(OpenPaymentsRecord.program_year).label("year_max"),
            )
            .where(OpenPaymentsRecord.hcp_npi.in_(npis))
            .group_by(OpenPaymentsRecord.hcp_npi)
        )
    ).all()
    payments = {
        row.hcp_npi: {
            "total": float(row.total or 0),
            "records": int(row.records or 0),
            "years": (
                f"{row.year_min}–{row.year_max}"
                if row.year_min and row.year_max and row.year_min != row.year_max
                else str(row.year_min or row.year_max or "")
            ),
        }
        for row in payment_rows
    }

    out: dict[str, PublicKOLIntel] = {}
    for npi in npis:
        hcp = hcps.get(npi)
        if hcp is None:
            continue
        brief = briefs.get(npi)
        ai_brief = None
        if brief and brief.brief_markdown.strip():
            ai_brief = {"whoTheyAre": brief.brief_markdown.strip()[:4000]}
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
