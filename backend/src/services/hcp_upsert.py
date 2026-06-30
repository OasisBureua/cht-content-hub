"""HCP upsert — CHT registration sync into hcps."""

from __future__ import annotations

import re

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from hcp_intel.models import HCP
from schemas.public import HCPUpsertRequest, HCPUpsertResponse

_NPI_RE = re.compile(r"^\d{10}$")


def normalize_npi(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if not _NPI_RE.fullmatch(digits):
        raise HTTPException(status_code=422, detail="NPI must be exactly 10 digits")
    return digits


def normalize_state(state: str | None) -> str | None:
    if not state:
        return None
    cleaned = state.strip().upper()
    return cleaned[:2] if cleaned else None


def _apply_fields(hcp: HCP, payload: HCPUpsertRequest) -> None:
    hcp.first_name = payload.first_name.strip() or "Unknown"
    hcp.last_name = payload.last_name.strip() or "Unknown"
    if payload.email is not None:
        hcp.email = payload.email.strip() or None
    if payload.specialty is not None:
        hcp.taxonomy = payload.specialty.strip() or None
    if payload.city is not None:
        hcp.city = payload.city.strip() or None
    if payload.state is not None:
        hcp.state = normalize_state(payload.state)
    if payload.zip is not None:
        hcp.zip = payload.zip.strip()[:10] or None
    if payload.institution is not None:
        hcp.hospital_affiliations = payload.institution.strip() or None
    if payload.source:
        hcp.source = payload.source.strip()


async def upsert_hcp(
    db: AsyncSession, payload: HCPUpsertRequest
) -> HCPUpsertResponse:
    npi = normalize_npi(payload.npi)
    existing = await db.get(HCP, npi)
    if existing is None:
        hcp = HCP(npi=npi, first_name="Unknown", last_name="Unknown")
        _apply_fields(hcp, payload)
        db.add(hcp)
        await db.flush()
        return HCPUpsertResponse(created=True, npi=npi)

    _apply_fields(existing, payload)
    await db.flush()
    return HCPUpsertResponse(created=False, npi=npi)
