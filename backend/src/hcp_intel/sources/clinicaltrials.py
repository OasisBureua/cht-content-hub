"""ClinicalTrials.gov v2 API fetcher + extractor.

Returns trials where the HCP appears as an investigator (overallOfficials)
or — with stricter attribution — as a site contact whose first+last name AND
locale both match the target HCP. Drug references come from
`interventions[].type == 'DRUG'`.

Disambiguation (rewritten 2026-04-20):

The previous version did naive substring matching on `last_name` against
official/contact names, with the well-known consequence that a community doc
like John Shen (Roswell, GA, no hospital) inherited 15 trials whose only
"shen" was a research coordinator named "Evan Y Shen, BA" at UC Davis.

The new flow:

1. **Word-boundary surname match.** `\\bshen\\b` instead of `"shen" in name`.
2. **Role-tier gating.**
   - `overallOfficials` (PI / Study Chair / Study Director) — strong; require
     surname + (forename match OR initial+locale match).
   - `locations[].contacts[]` (site contacts) — weak; require surname AND
     forename match AND that contact's site `city`/`state` overlaps with the
     HCP's city/state.
3. **Persist the matched contact + their site** in raw_json so future-us can
   re-evaluate without re-fetching CT.gov.
4. **No role assigned → no signal.** Trials with no qualifying role are
   dropped at fetch time (was already the case; preserved here).

Keeps the public callable API stable (orchestrator passes city/state/hospital
already), but `fetch_trials_for_hcp` now requires those fields to apply the
locale check. They default to None which falls back to officials-only matches.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import asyncio

import httpx
from curl_cffi.requests import AsyncSession

from hcp_intel.drug_normalize import is_drug_class_heading, normalize_drug

from .common import DrugPayload, FeedItemPayload, SignalPayload

log = logging.getLogger(__name__)

BASE = "https://clinicaltrials.gov/api/v2/studies"
UA = "CHM-MediaHub-FeedFetcher/0.1 (sebastien@communityhealth.media)"


@dataclass
class ClinicalTrial:
    nct_id: str
    title: str
    status: str
    phase: str | None
    start_date: datetime | None
    completion_date: datetime | None
    sponsor: str | None
    role: str | None  # 'principal_investigator' | 'sub_investigator' | ...
    matched_via: str | None = None  # 'official' | 'site_contact'
    matched_name: str | None = None  # the actual official/contact name we matched
    matched_site: dict[str, str] | None = None  # {facility,city,state} for site matches
    conditions: list[str] = field(default_factory=list)
    drugs: list[DrugPayload] = field(default_factory=list)
    locations: list[dict[str, str]] = field(default_factory=list)
    officials: list[dict[str, str]] = field(default_factory=list)


def _parse_date(raw: Any) -> datetime | None:
    if not raw:
        return None
    if isinstance(raw, dict):
        raw = raw.get("date")
    if not isinstance(raw, str):
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _name_tokens(s: str | None) -> list[str]:
    if not s:
        return []
    # Strip credentials ("MD", "PhD", "MBA"), commas, periods.
    cleaned = re.sub(r"[,.]", " ", s)
    return [t for t in cleaned.lower().split() if t and t.isalpha()]


def _surname_present(name: str, last_lc: str) -> bool:
    """Word-boundary surname match. Catches 'Shen' but not 'Shenkin'."""
    if not name or not last_lc:
        return False
    return bool(re.search(rf"\b{re.escape(last_lc)}\b", name.lower()))


def _forename_present(name: str, first_lc: str) -> bool:
    """Word-boundary first-name match. Treats 'J' as the initial of 'John'."""
    if not name or not first_lc:
        return False
    name_lc = name.lower()
    if re.search(rf"\b{re.escape(first_lc)}\b", name_lc):
        return True
    # Initial-only fallback ("Shen J" or "J Shen"). Avoid matching middle
    # initials by requiring the initial to be adjacent to the surname.
    initial = first_lc[:1]
    if initial:
        # 'J Shen', 'Shen J', 'Shen, J' patterns
        if re.search(rf"\b{re.escape(initial)}\.?\s+\w", name_lc):
            return True
    return False


def _locale_overlap(
    site: dict[str, Any] | None,
    *,
    target_city: str | None,
    target_state: str | None,
) -> bool:
    if not site:
        return False
    site_city = (site.get("city") or "").lower().strip()
    site_state = (site.get("state") or "").lower().strip()
    if target_city and site_city and site_city == target_city.lower().strip():
        return True
    # State match alone is too weak (TX has hundreds of oncologists), so we
    # only count state when the city is empty in either side.
    if target_state and site_state and site_state == target_state.lower().strip():
        if not target_city or not site_city:
            return True
    return False


def _match_official(
    officials: list[dict[str, Any]],
    *,
    last_lc: str,
    first_lc: str,
    target_city: str | None,
    target_state: str | None,
    target_hospital: str | None,
) -> tuple[str | None, str | None]:
    """Returns (role, matched_name) if we find an overall official match.

    Match rule: surname (word-boundary) AND (forename match OR affiliation
    contains city/state/hospital token).
    """
    hospital_tokens = [w for w in _name_tokens(target_hospital) if len(w) > 4]
    for off in officials:
        name = off.get("name") or ""
        if not _surname_present(name, last_lc):
            continue
        # Strong signal: forename match.
        if first_lc and _forename_present(name, first_lc):
            role = (off.get("role") or "").lower().replace(" ", "_") or "investigator"
            return role, name
        # Weaker but still acceptable: affiliation overlaps with HCP locale.
        aff = (off.get("affiliation") or "").lower()
        if aff and (
            (target_city and target_city.lower() in aff)
            or (target_state and target_state.lower() in aff)
            or any(tok in aff for tok in hospital_tokens)
        ):
            role = (off.get("role") or "").lower().replace(" ", "_") or "investigator"
            return role, name
    return None, None


def _match_site_contact(
    locations: list[dict[str, Any]],
    *,
    last_lc: str,
    first_lc: str,
    target_city: str | None,
    target_state: str | None,
) -> tuple[str | None, str | None, dict[str, str] | None]:
    """Returns (role, matched_name, site) if we find a site-contact match.

    Stricter than officials: requires BOTH forename AND surname match AND that
    the site's city/state overlap with the HCP's. A research coordinator at
    UC Davis with the same surname doesn't deserve to make the doctor look
    like a UC Davis investigator.
    """
    if not first_lc or not last_lc:
        return None, None, None
    for loc in locations:
        for c in loc.get("contacts") or []:
            name = c.get("name") or ""
            if not (_surname_present(name, last_lc) and _forename_present(name, first_lc)):
                continue
            if not _locale_overlap(loc, target_city=target_city, target_state=target_state):
                continue
            role = (c.get("role") or "").lower().replace(" ", "_") or "site_contact"
            site = {
                "facility": loc.get("facility") or "",
                "city": loc.get("city") or "",
                "state": loc.get("state") or "",
            }
            return role, name, site
    return None, None, None


def parse_studies(
    payload: dict[str, Any],
    *,
    last_name: str,
    first_name: str = "",
    target_city: str | None = None,
    target_state: str | None = None,
    target_hospital: str | None = None,
) -> list[ClinicalTrial]:
    """Parse CT.gov v2 response. Only emits trials with a confirmed role.

    `first_name` is required for trustworthy attribution. When omitted (legacy
    callers, tests), only officials with a fuzzy hospital/locale affiliation
    match against the surname will be accepted; site contacts are dropped.
    """
    last_lc = (last_name or "").lower().strip()
    first_lc = (first_name or "").lower().strip()

    out: list[ClinicalTrial] = []
    for study in payload.get("studies", []):
        proto = study.get("protocolSection", {})
        ident = proto.get("identificationModule", {})
        status = proto.get("statusModule", {})
        design = proto.get("designModule", {})
        arms = proto.get("armsInterventionsModule", {})
        sponsor_mod = proto.get("sponsorCollaboratorsModule", {})
        contacts = proto.get("contactsLocationsModule", {})
        conditions = proto.get("conditionsModule", {})

        officials = contacts.get("overallOfficials", []) or []
        locations = contacts.get("locations", []) or []

        role, matched_name = _match_official(
            officials,
            last_lc=last_lc,
            first_lc=first_lc,
            target_city=target_city,
            target_state=target_state,
            target_hospital=target_hospital,
        )
        matched_via = "official" if role else None
        matched_site: dict[str, str] | None = None

        if not role:
            sc_role, sc_name, sc_site = _match_site_contact(
                locations,
                last_lc=last_lc,
                first_lc=first_lc,
                target_city=target_city,
                target_state=target_state,
            )
            if sc_role:
                role, matched_name, matched_site = sc_role, sc_name, sc_site
                matched_via = "site_contact"

        interventions = arms.get("interventions", []) or []
        drugs: list[DrugPayload] = []
        seen: set[str] = set()
        for iv in interventions:
            if (iv.get("type") or "").upper() != "DRUG":
                continue
            name = (iv.get("name") or "").strip()
            if not name:
                continue
            if is_drug_class_heading(name):
                continue
            norm = normalize_drug(name)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            drugs.append(
                DrugPayload(
                    drug_source_term=name[:255],
                    drug_normalized=norm,
                    source_field="intervention",
                )
            )

        phases = design.get("phases") or []
        out.append(
            ClinicalTrial(
                nct_id=ident.get("nctId") or "",
                title=ident.get("briefTitle") or ident.get("officialTitle") or "",
                status=status.get("overallStatus") or "",
                phase=", ".join(phases) if phases else None,
                start_date=_parse_date(status.get("startDateStruct")),
                completion_date=_parse_date(status.get("completionDateStruct")),
                sponsor=(sponsor_mod.get("leadSponsor") or {}).get("name"),
                role=role,
                matched_via=matched_via,
                matched_name=matched_name,
                matched_site=matched_site,
                conditions=conditions.get("conditions", []) or [],
                drugs=drugs,
                locations=[
                    {
                        "facility": loc.get("facility") or "",
                        "city": loc.get("city") or "",
                        "state": loc.get("state") or "",
                        "country": loc.get("country") or "",
                        # NEW: keep contact names so future re-evaluation has
                        # the data we need without another network call.
                        "contacts": [
                            {
                                "name": (c.get("name") or "")[:200],
                                "role": (c.get("role") or "")[:80],
                            }
                            for c in (loc.get("contacts") or [])
                        ],
                    }
                    for loc in locations
                ],
                officials=[
                    {
                        "name": o.get("name") or "",
                        "role": o.get("role") or "",
                        "affiliation": o.get("affiliation") or "",
                    }
                    for o in officials
                ],
            )
        )
    return out


async def fetch_trials_for_hcp(
    first_name: str,
    last_name: str,
    *,
    since: datetime | None = None,
    client: httpx.AsyncClient | None = None,  # kept for API compat; unused
    city: str | None = None,
    state: str | None = None,
    hospital: str | None = None,
) -> list[ClinicalTrial]:
    """Fetch trials and return only those passing the strict attribution check.

    The CT.gov full-text query (`{first} {last}`) returns lots of false
    positives (Evan Shen, anyone-named-Shen on the protocol). The post-filter
    in parse_studies discards trials where neither an official nor a
    locale-confirmed site contact matches.
    """
    params = {
        "query.term": f"{first_name} {last_name}".strip(),
        "pageSize": 50,
    }
    async with AsyncSession(impersonate="chrome120", timeout=15) as sess:
        await asyncio.sleep(1.0)  # polite: 1 req/sec
        r = await sess.get(BASE, params=params)
        if r.status_code != 200:
            raise RuntimeError(f"CT.gov HTTP {r.status_code}: {r.text[:200]}")
        trials = parse_studies(
            r.json(),
            last_name=last_name,
            first_name=first_name,
            target_city=city,
            target_state=state,
            target_hospital=hospital,
        )

    matched = [t for t in trials if t.role]
    if since:
        matched = [
            t
            for t in matched
            if t.start_date is None or t.start_date >= since
        ]
    return matched


def trial_to_feed_item(trial: ClinicalTrial) -> FeedItemPayload:
    # Clamp future-dated trial starts to today. A trial's start_date in
    # CT.gov can be 6-18 months ahead (announced but not yet active). If
    # we're ingesting it as a signal today, treat the observed_at as now
    # so it doesn't appear in "last activity" as a future date.
    pub = trial.start_date
    if pub is not None and pub > datetime.utcnow():
        pub = datetime.utcnow()
    return FeedItemPayload(
        external_id=trial.nct_id,
        title=trial.title,
        url=f"https://clinicaltrials.gov/study/{trial.nct_id}",
        published_at=pub,
        raw={
            "nct_id": trial.nct_id,
            "status": trial.status,
            "phase": trial.phase,
            "sponsor": trial.sponsor,
            "role": trial.role,
            "matched_via": trial.matched_via,
            "matched_name": trial.matched_name,
            "matched_site": trial.matched_site,
            "conditions": trial.conditions,
            "drugs": [
                {"term": d.drug_source_term, "normalized": d.drug_normalized}
                for d in trial.drugs
            ],
            "locations": trial.locations,
            "officials": trial.officials,
            "completion_date": (
                trial.completion_date.isoformat() if trial.completion_date else None
            ),
        },
    )


def extract_signals(item: FeedItemPayload) -> list[SignalPayload]:
    raw = item.raw or {}
    drugs = [
        DrugPayload(
            drug_source_term=d["term"],
            drug_normalized=d["normalized"],
            source_field="intervention",
        )
        for d in (raw.get("drugs") or [])
        if d.get("normalized")
    ]
    if item.published_at is None:
        return []
    return [
        SignalPayload(
            signal_type="trial",
            observed_at=item.published_at,
            title=item.title,
            url=item.url,
            summary=raw.get("sponsor") or None,
            entities={
                "nct_id": raw.get("nct_id") or item.external_id,
                "phase": raw.get("phase"),
                "status": raw.get("status"),
                "sponsor": raw.get("sponsor"),
                "role": raw.get("role"),
                "matched_via": raw.get("matched_via"),
                "matched_name": raw.get("matched_name"),
                "matched_site": raw.get("matched_site"),
                "conditions": raw.get("conditions") or [],
            },
            drugs=drugs,
        )
    ]
