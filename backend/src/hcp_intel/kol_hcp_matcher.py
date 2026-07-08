"""KOL → HCP matcher.

Bridges the legacy `kols` table (content-side identity) with `hcps` (HCP
Intel roster keyed on NPI). Once a KOL is linked to an NPI, their HCP
profile surfaces content appearances + publications + engagement + Rx
shifts in one place.

Matching signals:
- Name: split KOL.name into first/last (or use last word as surname)
  and compare to hcps.first_name/last_name. Word-boundary regex.
- Institution: KOL.institution token overlap with hcps.hospital_affiliations.
- Credential: if KOL.title contains "MD" and hcps.credential matches,
  weak positive (most oncologists are MDs so low signal).

Scoring:
  +3  last-name match (required)
  +2  first-name match (word-boundary in KOL.name)
  +3  institution token match
  +1  state match (if KOL mentions a known city/state)
  -10 last-name mismatch (required)

Gates:
  high      score >= 7 AND gap >= 3  → auto_locked
  medium    score >= 5 AND gap >= 2  → needs_review
  ambiguous otherwise                → needs_review
  none      no candidates            → no_match

Confidence in [0, 1] = top_score / max_score (max 9).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from hcp_intel.models import HCP
from models.kol import KOL

log = logging.getLogger(__name__)

_MAX_SCORE = 9

_INST_STOPWORDS = {
    "the", "of", "for", "and", "at", "in", "a", "an",
    "medical", "center", "centers", "hospital", "hospitals",
    "health", "system", "systems", "clinic", "clinics",
    "cancer", "institute", "university", "research", "memorial",
}


@dataclass
class HCPCandidate:
    npi: str
    first_name: str
    last_name: str
    hospital_affiliations: str | None
    state: str | None
    score: int
    score_notes: list[str]


@dataclass
class KOLMatchResult:
    hcp_npi: str | None
    status: str  # 'auto_locked' | 'needs_review' | 'no_match'
    confidence: float
    candidates: list[HCPCandidate] = field(default_factory=list)


def _split_kol_name(name: str) -> tuple[str, str]:
    """Extract (first, last) from a free-form KOL name like 'Dr. Jason Mouabbi, MD'."""
    if not name:
        return ("", "")
    cleaned = name.strip()
    cleaned = re.sub(r"^dr\.?\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r",?\s*(md|phd|do|np|pa|rn)\.?$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[,]", "", cleaned)
    parts = cleaned.split()
    if not parts:
        return ("", "")
    if len(parts) == 1:
        return ("", parts[0])
    return (parts[0], parts[-1])


def _inst_tokens(inst: str | None) -> set[str]:
    if not inst:
        return set()
    parts = re.split(r"[,;/|&\-\s]+", inst.lower())
    return {p for p in parts if p and len(p) >= 5 and p not in _INST_STOPWORDS}


def _score_candidate(
    hcp: HCP, *, kol_first: str, kol_last: str, kol_inst: str | None,
) -> tuple[int, list[str]]:
    score = 0
    notes: list[str] = []

    # Last-name match (required)
    kol_last_lc = kol_last.lower().strip()
    hcp_last_lc = (hcp.last_name or "").lower().strip()
    if kol_last_lc and hcp_last_lc == kol_last_lc:
        score += 3
        notes.append(f"+3 last-name match ({kol_last})")
    else:
        score -= 10
        notes.append(f"-10 last-name mismatch ({kol_last} vs {hcp.last_name})")
        return score, notes  # no point continuing

    # First-name match
    if kol_first:
        kol_first_lc = kol_first.lower().strip()
        hcp_first_lc = (hcp.first_name or "").lower().strip()
        if hcp_first_lc and (
            kol_first_lc == hcp_first_lc
            or hcp_first_lc.startswith(kol_first_lc + " ")
            or kol_first_lc.startswith(hcp_first_lc + " ")
            or hcp_first_lc == kol_first_lc[0]  # KOL 'Jason' vs HCP 'J' initial
        ):
            score += 2
            notes.append(f"+2 first-name match ({kol_first})")
        else:
            # First initial match is neutral (some HCPs store initials)
            if hcp_first_lc and hcp_first_lc[0] == kol_first_lc[0]:
                notes.append(f"~0 first-initial only ({kol_first[0]})")
            else:
                score -= 3
                notes.append(f"-3 first-name mismatch ({kol_first} vs {hcp.first_name})")

    # Institution match
    kol_inst_tokens = _inst_tokens(kol_inst)
    hcp_inst_tokens = _inst_tokens(hcp.hospital_affiliations)
    if kol_inst_tokens and hcp_inst_tokens:
        overlap = kol_inst_tokens & hcp_inst_tokens
        if overlap:
            score += 3
            notes.append(f"+3 institution match ({next(iter(overlap))})")

    return score, notes


def _status_from_scored(scored: list[HCPCandidate]) -> tuple[str, float]:
    if not scored:
        return ("no_match", 0.0)
    top = scored[0]
    second = scored[1] if len(scored) > 1 else None
    confidence = max(0.0, min(1.0, top.score / _MAX_SCORE))
    if top.score < 0:
        return ("no_match", 0.0)
    gap = top.score - (second.score if second else -999)
    # Sole-candidate exact-name-match auto-lock: exact first + last match
    # (+2+3=5) with no competing candidate is a strong signal for KOL tables
    # that have no institution data to disambiguate further. Relevant for
    # the CHM KOL roster which stores only "Dr. Jason Mouabbi".
    if top.score >= 5 and second is None:
        return ("auto_locked", confidence)
    if top.score >= 7 and gap >= 3:
        return ("auto_locked", confidence)
    # Exact-name match with clear gap over competing candidates.
    if top.score >= 5 and gap >= 3:
        return ("auto_locked", confidence)
    if top.score >= 5:
        return ("needs_review", confidence)
    return ("no_match", confidence)


async def match_kol(db: AsyncSession, kol: KOL) -> KOLMatchResult:
    """Resolve one KOL to an HCP NPI (if possible)."""
    kol_first, kol_last = _split_kol_name(kol.name or "")
    if not kol_last:
        return KOLMatchResult(hcp_npi=None, status="no_match", confidence=0.0)

    # Fetch HCPs sharing the last name (case-insensitive).
    stmt = select(HCP).where(HCP.last_name.ilike(kol_last))
    hcps = list((await db.execute(stmt)).scalars().all())
    if not hcps:
        return KOLMatchResult(hcp_npi=None, status="no_match", confidence=0.0)

    scored: list[HCPCandidate] = []
    for hcp in hcps:
        score, notes = _score_candidate(
            hcp, kol_first=kol_first, kol_last=kol_last,
            kol_inst=kol.institution,
        )
        scored.append(HCPCandidate(
            npi=hcp.npi,
            first_name=hcp.first_name,
            last_name=hcp.last_name,
            hospital_affiliations=hcp.hospital_affiliations,
            state=hcp.state,
            score=score,
            score_notes=notes,
        ))
    scored.sort(key=lambda c: c.score, reverse=True)

    status, confidence = _status_from_scored(scored)
    hcp_npi = scored[0].npi if status == "auto_locked" else None

    return KOLMatchResult(
        hcp_npi=hcp_npi,
        status=status,
        confidence=confidence,
        candidates=scored[:5],
    )


async def resolve_and_persist(db: AsyncSession, kol: KOL) -> KOLMatchResult:
    """Match + write back to kols table. Does NOT commit — caller controls tx."""
    result = await match_kol(db, kol)
    from dataclasses import asdict
    await db.execute(
        update(KOL)
        .where(KOL.id == kol.id)
        .values(
            hcp_npi=result.hcp_npi,
            hcp_match_status=result.status,
            hcp_match_confidence=result.confidence,
            hcp_candidates=[asdict(c) for c in result.candidates],
            hcp_resolved_at=datetime.utcnow(),
        )
    )
    return result
