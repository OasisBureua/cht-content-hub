"""OpenAlex author resolver + works fetcher.

Replaces the weak name+initial PubMed attribution with stable OpenAlex
`author_id` locking. Once an HCP is resolved to an author_id, future polls
are deterministic — no re-disambiguation, no name collisions.

Flow:
1. `resolve_author(first, last, hospital)` — search + score + ORCID-dedupe.
   Returns (author_id, confidence, candidates) where confidence is one of
   'high' | 'medium' | 'ambiguous' | 'none'.
2. `fetch_works(author_id, since)` — deterministic poll for new papers.

Scoring (per candidate):
  +3  an institution name contains the expected hospital substring
  +2  has at least one oncology-related concept
  +1  works_count > 20 (filters students / one-paper authors)
  -5  no oncology concepts at all

Gates:
  high      top_score >= 5 AND (top - second) >= 3   → auto-lock
  medium    top_score >= 3 AND (top - second) >= 2   → needs review
  ambiguous otherwise (but top_score >= 0)           → needs review
  none      no candidates, or top_score < 0          → no_match

Polite pool: include `mailto` param for 10 req/sec; no auth key required.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from .common import DrugPayload, FeedItemPayload, SignalPayload

log = logging.getLogger(__name__)

BASE = "https://api.openalex.org"
MAILTO = "sebastien@communityhealth.media"
UA = f"CHM-MediaHub-FeedFetcher/0.1 ({MAILTO})"

# OpenAlex API key (premium pool, much higher rate limit). Optional — when
# absent we fall back to the polite pool (~10 req/sec via the mailto param).
_API_KEY = os.environ.get("OPENALEX_API_KEY", "").strip() or None

SIGNAL_TYPE = "publication"

# Polite-pool rate: OpenAlex documents 10 req/sec with mailto, but in practice
# sustained traffic at >1-2 req/sec trips their internal rate limiter into
# 429s (observed 2026-04-27 on sustained backfill). 1s delay = ~1 req/sec
# is the conservative default. Override with OPENALEX_RATE_DELAY_S=<seconds>
# (e.g. 0.3 for premium pool when key works).
_RATE_DELAY_S = float(os.environ.get("OPENALEX_RATE_DELAY_S", "1.0"))

_ONCOLOGY_TERMS = (
    "oncology", "cancer", "tumor", "tumour", "chemotherapy",
    "carcinoma", "metastasis", "neoplasm", "leukemia", "lymphoma",
    "hematology",
)


@dataclass
class AuthorCandidate:
    """One OpenAlex author candidate, scored against an HCP."""

    author_id: str  # "A5012345678" (bare, not full URL)
    display_name: str
    orcid: str | None  # "0000-0002-1234-5678" (bare)
    works_count: int
    cited_by_count: int
    institutions: list[dict[str, Any]]  # [{display_name, ror, country_code}, ...]
    concepts: list[str]  # top concept display names
    score: int
    score_notes: list[str]


@dataclass
class ResolveResult:
    """Outcome of resolving one HCP to an OpenAlex author_id."""

    author_id: str | None
    confidence: str  # 'high' | 'medium' | 'ambiguous' | 'none'
    candidates: list[AuthorCandidate] = field(default_factory=list)


@dataclass
class WorkPayload:
    """One OpenAlex work, ready to upsert as a feed_item."""

    openalex_id: str  # "W4012345678" (bare)
    doi: str | None  # "10.1056/NEJMoa2112651"
    title: str
    publication_date: datetime | None
    journal: str | None
    authors: list[str]
    is_first_author: bool
    is_last_author: bool
    concepts: list[str]
    url: str | None  # best landing-page URL
    raw: dict[str, Any]


# ─── low-level HTTP ─────────────────────────────────────────────────────────


async def _get(
    client: httpx.AsyncClient, path: str, params: dict[str, Any]
) -> dict[str, Any]:
    """GET with rate-limit delay + retry on 429 (exponential backoff)."""
    await asyncio.sleep(_RATE_DELAY_S)
    params = {**params, "mailto": MAILTO}
    headers = {"User-Agent": UA}
    if _API_KEY:
        # Premium pool — higher rate limit. Send key as Authorization Bearer
        # AND as `api_key` query param (OpenAlex accepts both; some routes
        # only honor the param). Belt-and-suspenders.
        headers["Authorization"] = f"Bearer {_API_KEY}"
        params["api_key"] = _API_KEY
    for attempt in range(3):
        r = await client.get(
            f"{BASE}{path}",
            params=params,
            headers=headers,
            timeout=30.0,
        )
        if r.status_code == 429:
            # Exponential backoff: 1s, 4s, 16s
            wait = 4 ** attempt
            log.warning("openalex 429 on %s — backing off %ds", path, wait)
            await asyncio.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()  # final attempt failed, raise
    return r.json()


def _bare_id(full_id: str | None) -> str | None:
    """Strip 'https://openalex.org/' prefix — keep just 'A123' / 'W456'."""
    if not full_id:
        return None
    return full_id.rsplit("/", 1)[-1]


def _bare_orcid(full_orcid: str | None) -> str | None:
    if not full_orcid:
        return None
    return full_orcid.rsplit("/", 1)[-1]


# ─── scoring ────────────────────────────────────────────────────────────────


def _score_candidate(
    raw: dict[str, Any],
    hospital: str | None,
    *,
    expected_last_name: str | None = None,
    expected_first_name: str | None = None,
) -> tuple[int, list[str]]:
    """Score one raw OpenAlex author record against expected HCP identity."""
    score = 0
    notes: list[str] = []

    insts = raw.get("last_known_institutions") or []
    inst_names = [(i.get("display_name") or "") for i in insts]

    # Last-name match — required. OpenAlex fuzzy-search returns unrelated
    # authors who happen to share an institution (e.g. searching 'Larisa
    # Greenberg' at Allegheny also surfaces 'Athanasios Colonias'). Require
    # the HCP's last name to appear in the candidate's display_name.
    display_name = (raw.get("display_name") or "").lower()
    if expected_last_name:
        last_lc = expected_last_name.lower().strip()
        if last_lc and re.search(rf"\b{re.escape(last_lc)}\b", display_name):
            score += 2
            notes.append(f"+2 last-name match ({expected_last_name})")
        else:
            score -= 10
            notes.append(f"-10 last-name mismatch (got {raw.get('display_name')!r})")

    # First-name match (or initial). Handles 'Aabha Oza' vs 'Amit M. Oza' —
    # same surname + institution but different person. First-initial counts
    # as a weak match, full first-name is a strong one.
    if expected_first_name:
        first_lc = expected_first_name.lower().strip().rstrip(".")
        # Strip common prefixes
        first_lc = first_lc.split()[0] if first_lc else ""
        if first_lc and len(first_lc) >= 2:
            if re.search(rf"\b{re.escape(first_lc)}\b", display_name):
                score += 2
                notes.append(f"+2 first-name match ({expected_first_name})")
            elif re.search(rf"\b{re.escape(first_lc[0])}\w*\b", display_name):
                # First initial at least matches — weak positive
                score += 0  # neutral
                notes.append(f"~0 first-initial only ({expected_first_name[0]})")
            else:
                score -= 3
                notes.append(f"-3 first-name mismatch (got {raw.get('display_name')!r})")

    if hospital:
        hosp_lc = hospital.lower()
        # Match on any non-trivial token of the hospital name (handles
        # "Dana-Farber Cancer Institute" vs "Dana-Farber"). Require tokens
        # >= 5 chars to avoid false matches like "Dana" hitting "Dana (US)"
        # on unrelated NYPD institution records.
        hosp_tokens = [
            t for t in re.split(r"[,;/|&\-\s]+", hosp_lc)
            if len(t) >= 5 and t not in {
                "center", "hospital", "medical", "health", "cancer",
                "institute", "university", "research", "memorial",
            }
        ]
        matched = False
        if hosp_tokens:
            for n in inst_names:
                nl = n.lower()
                # Word-boundary match: token must appear as a full word, not
                # a prefix of a longer word. Stops "dana" in "dana-farber"
                # from matching "dana (united states)" (where "dana" is also
                # a full word but NYPD has no oncology context — that gets
                # filtered elsewhere; this just tightens the institution match).
                if any(re.search(rf"\b{re.escape(t)}\b", nl) for t in hosp_tokens):
                    matched = True
                    break
        # Full-string fallback
        if not matched and any(hosp_lc in n.lower() for n in inst_names):
            matched = True
        if matched:
            score += 3
            notes.append(f"+3 inst match ({hospital})")

    concept_names = [
        (c.get("display_name") or "")
        for c in (raw.get("x_concepts") or [])
    ]
    onco_hits = [
        c for c in concept_names
        if any(t in c.lower() for t in _ONCOLOGY_TERMS)
    ]
    if onco_hits:
        score += 2
        notes.append(f"+2 oncology ({onco_hits[0]})")
    else:
        score -= 5
        notes.append("-5 no oncology concepts")

    if (raw.get("works_count") or 0) > 20:
        score += 1
        notes.append("+1 works>20")

    return score, notes


def _to_candidate(raw: dict[str, Any], score: int, notes: list[str]) -> AuthorCandidate:
    insts = [
        {
            "display_name": i.get("display_name"),
            "ror": _bare_id(i.get("ror")),
            "country_code": i.get("country_code"),
        }
        for i in (raw.get("last_known_institutions") or [])
    ]
    concepts = [
        (c.get("display_name") or "")
        for c in (raw.get("x_concepts") or [])[:5]
    ]
    return AuthorCandidate(
        author_id=_bare_id(raw.get("id")) or "",
        display_name=raw.get("display_name") or "",
        orcid=_bare_orcid(raw.get("orcid")),
        works_count=int(raw.get("works_count") or 0),
        cited_by_count=int(raw.get("cited_by_count") or 0),
        institutions=insts,
        concepts=concepts,
        score=score,
        score_notes=notes,
    )


def _normalize_name(name: str) -> str:
    """Strip punctuation, lowercase, collapse whitespace — so 'Sara M Tolaney'
    and 'Sara M. Tolaney' hash the same."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", name.lower())).strip()


def _primary_inst(raw: dict[str, Any]) -> str | None:
    insts = raw.get("last_known_institutions") or []
    if not insts:
        return None
    return (insts[0].get("display_name") or "").lower() or None


def _dedupe_by_orcid(raws: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse records that belong to the same person. OpenAlex has known
    author-merge lag — the same physician can have many `A…` IDs, often
    with only one carrying an ORCID and the rest being 1-work shadow records.

    Two-pass dedupe:
    1. Collapse by ORCID (if two records share an ORCID, keep highest works).
    2. Collapse by (normalized_display_name, primary_institution) — catches
       the shadow records that have no ORCID but the same name + institution
       as a known author.
    """
    # Pass 1: ORCID
    by_orcid: dict[str, dict[str, Any]] = {}
    no_orcid: list[dict[str, Any]] = []
    for r in raws:
        orcid = _bare_orcid(r.get("orcid"))
        if not orcid:
            no_orcid.append(r)
            continue
        existing = by_orcid.get(orcid)
        if existing is None or (r.get("works_count") or 0) > (existing.get("works_count") or 0):
            by_orcid[orcid] = r
    first_pass = list(by_orcid.values()) + no_orcid

    # Pass 2: (name, primary_institution). Only collapse if the institution
    # is present — otherwise two different "John Smith"s would get merged.
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    no_inst: list[dict[str, Any]] = []
    for r in first_pass:
        name_key = _normalize_name(r.get("display_name") or "")
        inst_key = _primary_inst(r)
        if not name_key or not inst_key:
            no_inst.append(r)
            continue
        key = (name_key, inst_key)
        existing = by_key.get(key)
        if existing is None or (r.get("works_count") or 0) > (existing.get("works_count") or 0):
            by_key[key] = r
    return list(by_key.values()) + no_inst


def _classify(scored: list[AuthorCandidate]) -> str:
    if not scored:
        return "none"
    top = scored[0]
    second = scored[1] if len(scored) > 1 else None
    if top.score < 0:
        return "none"
    if second is None:
        return "high" if top.score >= 5 else "medium" if top.score >= 3 else "ambiguous"
    # Works-count dominance: OpenAlex author-record fragmentation means the
    # "real" author often has 100-1000x more works than shadow records. If
    # the top record dwarfs #2 AND has a strong score, it's clearly the
    # primary record for this person — auto-lock even if scores are close.
    score_gap = top.score - second.score
    # Works-count dominance auto-lock requires a strong score (>=9 means
    # both name + hospital + oncology all matched, or name + first-name +
    # oncology + works), not just "last name + oncology + many works".
    # Otherwise we lock in unrelated authors who share a surname.
    dominant = (
        top.works_count >= 50
        and top.works_count >= second.works_count * 10
        and top.score >= 9
    )
    if dominant:
        return "high"
    if top.score >= 7 and score_gap >= 3:
        return "high"
    if top.score >= 5 and score_gap >= 2:
        return "medium"
    return "ambiguous"


# ─── resolver ───────────────────────────────────────────────────────────────


async def _search_authors(
    client: httpx.AsyncClient,
    first: str,
    last: str,
    *,
    us_only: bool,
    per_page: int = 10,
) -> list[dict[str, Any]]:
    name = f"{first} {last}".strip()
    params: dict[str, Any] = {"search": name, "per-page": per_page}
    if us_only:
        params["filter"] = "last_known_institutions.country_code:US"
    data = await _get(client, "/authors", params)
    return data.get("results", []) or []


async def resolve_author(
    first_name: str,
    last_name: str,
    hospital: str | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> ResolveResult:
    """Search OpenAlex for the given HCP and score the candidates.

    Retries without the US country filter if the US-filtered search returns
    no usable candidates (handles ROR-country quirks like Sarah Cannon
    resolving to GB, or records missing last_known_institutions).
    """
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=30.0)
    try:
        raws = await _search_authors(client, first_name, last_name, us_only=True)
        if not raws or all((r.get("works_count") or 0) < 5 for r in raws):
            # Fallback: try without country filter — then re-filter post-hoc
            # to prefer US institutions if any appear.
            raws_all = await _search_authors(
                client, first_name, last_name, us_only=False
            )
            if raws_all:
                raws = raws_all

        if not raws:
            return ResolveResult(author_id=None, confidence="none")

        raws = _dedupe_by_orcid(raws)

        scored: list[AuthorCandidate] = []
        for r in raws:
            sc, notes = _score_candidate(
                r, hospital,
                expected_last_name=last_name,
                expected_first_name=first_name,
            )
            scored.append(_to_candidate(r, sc, notes))
        scored.sort(key=lambda c: c.score, reverse=True)

        confidence = _classify(scored)
        author_id = scored[0].author_id if confidence in ("high",) else None

        return ResolveResult(
            author_id=author_id,
            confidence=confidence,
            candidates=scored[:5],
        )
    finally:
        if own:
            await client.aclose()


# ─── works fetcher ──────────────────────────────────────────────────────────


def _parse_work(raw: dict[str, Any], author_id: str) -> WorkPayload | None:
    """Convert one OpenAlex work record to a WorkPayload."""
    work_id = _bare_id(raw.get("id"))
    if not work_id:
        return None

    title = (raw.get("title") or raw.get("display_name") or "").strip()
    if not title:
        return None

    pub_date = None
    pub_date_raw = raw.get("publication_date")
    if pub_date_raw:
        try:
            pub_date = datetime.strptime(pub_date_raw, "%Y-%m-%d")
        except (TypeError, ValueError):
            pub_date = None
    # Clamp future dates (same defensive pattern as pubmed.py).
    if pub_date is not None and pub_date > datetime.utcnow():
        pub_date = datetime.utcnow()

    doi_raw = raw.get("doi")
    doi = doi_raw.rsplit("doi.org/", 1)[-1] if doi_raw else None

    primary = raw.get("primary_location") or {}
    source = primary.get("source") or {}
    journal = source.get("display_name")

    authorships = raw.get("authorships") or []
    authors: list[str] = []
    is_first = False
    is_last = False
    for i, a in enumerate(authorships):
        author_obj = a.get("author") or {}
        aid = _bare_id(author_obj.get("id"))
        name = author_obj.get("display_name") or ""
        authors.append(name)
        if aid == author_id:
            if i == 0:
                is_first = True
            if i == len(authorships) - 1:
                is_last = True

    concepts = [
        (c.get("display_name") or "")
        for c in (raw.get("concepts") or [])[:5]
    ]

    url = primary.get("landing_page_url") or raw.get("id")

    return WorkPayload(
        openalex_id=work_id,
        doi=doi,
        title=title,
        publication_date=pub_date,
        journal=journal,
        authors=authors,
        is_first_author=is_first,
        is_last_author=is_last,
        concepts=concepts,
        url=url,
        raw=raw,
    )


async def fetch_works(
    author_id: str,
    since: datetime | None = None,
    *,
    client: httpx.AsyncClient | None = None,
    max_results: int = 200,
) -> list[WorkPayload]:
    """Fetch works for a locked OpenAlex author_id, optionally filtered to
    publications after `since`.
    """
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=30.0)
    try:
        filters = [f"author.id:{author_id}"]
        if since is not None:
            filters.append(f"from_publication_date:{since.date().isoformat()}")

        results: list[WorkPayload] = []
        cursor = "*"
        while cursor and len(results) < max_results:
            data = await _get(
                client,
                "/works",
                {
                    "filter": ",".join(filters),
                    "per-page": 50,
                    "sort": "publication_date:desc",
                    "cursor": cursor,
                },
            )
            for raw in data.get("results", []) or []:
                parsed = _parse_work(raw, author_id)
                if parsed is not None:
                    results.append(parsed)
                if len(results) >= max_results:
                    break
            cursor = (data.get("meta") or {}).get("next_cursor")
        return results
    finally:
        if own:
            await client.aclose()


# ─── feed_item conversion (for orchestrator integration) ────────────────────


def work_to_feed_item(work: WorkPayload) -> FeedItemPayload:
    """Convert a WorkPayload to a FeedItemPayload for persistence."""
    return FeedItemPayload(
        external_id=work.openalex_id,
        title=work.title,
        url=work.url,
        published_at=work.publication_date,
        raw={
            "openalex_id": work.openalex_id,
            "doi": work.doi,
            "journal": work.journal,
            "authors": work.authors,
            "is_first_author": work.is_first_author,
            "is_last_author": work.is_last_author,
            "concepts": work.concepts,
        },
    )


def extract_signals(item: FeedItemPayload) -> list[SignalPayload]:
    """Convert a stored OpenAlex feed_item back into a publication signal.

    OpenAlex doesn't carry MeSH drug tags directly (those are PubMed-specific),
    but we keep the same `signal_type='publication'` so the FE renders OpenAlex
    pubs identically to PubMed pubs in the Background tab. Drug attribution on
    OpenAlex pubs comes later via concept-mapping if/when we need it.
    """
    if item.published_at is None:
        return []
    raw = item.raw or {}
    entities = {
        "openalex_id": raw.get("openalex_id") or item.external_id,
        "doi": raw.get("doi"),
        "journal": raw.get("journal"),
        "is_first_author": bool(raw.get("is_first_author")),
        "is_last_author": bool(raw.get("is_last_author")),
        "concepts": raw.get("concepts"),
    }
    return [
        SignalPayload(
            signal_type=SIGNAL_TYPE,
            observed_at=item.published_at,
            title=item.title,
            url=item.url,
            summary=raw.get("journal") or None,
            entities=entities,
            drugs=[],
        )
    ]
